from utime import ticks_ms, ticks_diff, gmtime, time
from math import ceil
import rp2
import network
from ubinascii import hexlify
import config
from lib.ulogging import uLogger
from lib.utils import StatusLED
from asyncio import sleep, create_task
from machine import RTC
from socket import socket, AF_INET, SOCK_DGRAM, getaddrinfo
import struct
import gc

class WirelessNetwork:

    def __init__(self, on_time_sync=None) -> None:
        self.log = uLogger("WIFI")
        self.log.info("Initializing Wireless Network")
        self.on_time_sync = on_time_sync
        self.status_led = StatusLED()
        self.wifi_ssid = config.WIFI_SSID
        self.wifi_password = config.WIFI_PASSWORD
        self.wifi_country = config.WIFI_COUNTRY
        rp2.country(self.wifi_country)
        self.disable_power_management = 0xa11140
        self.led_retry_backoff_frequency = 4
        
        # Reference: https://datasheets.raspberrypi.com/picow/connecting-to-the-internet-with-pico-w.pdf
        self.CYW43_LINK_DOWN = 0
        self.CYW43_LINK_JOIN = 1
        self.CYW43_LINK_NOIP = 2
        self.CYW43_LINK_UP = 3
        self.CYW43_LINK_FAIL = -1
        self.CYW43_LINK_NONET = -2
        self.CYW43_LINK_BADAUTH = -3
        self.status_names = {
        self.CYW43_LINK_DOWN: "Link is down",
        self.CYW43_LINK_JOIN: "Connected to wifi",
        self.CYW43_LINK_NOIP: "Connected to wifi, but no IP address",
        self.CYW43_LINK_UP: "Connect to wifi with an IP address",
        self.CYW43_LINK_FAIL: "Connection failed",
        self.CYW43_LINK_NONET: "No matching SSID found (could be out of range, or down)",
        self.CYW43_LINK_BADAUTH: "Authenticatation failure",
        }
        self.ip = "Unknown"
        self.subnet = "Unknown"
        self.gateway = "Unknown"
        self.dns = "Unknown"
        self.ntp_last_synced_timestamp = 0
        self.ntp_sync_status = False
        self.prtc_sync_status = False
        self.network_check_in_progress = False
        self.ntp_sync_in_progress = False
        self.ntp_host = "uk.pool.ntp.org"
        self.ntp_servers = []
        self.ntp_port = 123
        self.ntp_server_index = 0
        self.ntp_address = None
        self.last_network_state = None
        
        if config.NTP_SYNC_INTERVAL_SECONDS < 60:
            self.log.warn("NTP sync interval too low, setting to minimum of 60 seconds")
            self.NTP_SYNC_INTERVAL_SECONDS = 60
        else:
            self.NTP_SYNC_INTERVAL_SECONDS = config.NTP_SYNC_INTERVAL_SECONDS

        self.configure_wifi()

    def refresh_ntp_servers(self) -> bool:
        """
        Resolve and cache NTP server IP addresses from configured hostname.

        Returns:
            bool: True when at least one IPv4 address is resolved, else False.
        """
        if not self.has_valid_network_config():
            self.log.warn("NTP DNS refresh skipped: network lacks DHCP IP/DNS configuration")
            return False

        try:
            addrinfo = getaddrinfo(self.ntp_host, self.ntp_port, AF_INET, SOCK_DGRAM)
            resolved_servers = []
            for entry in addrinfo:
                ip_address = entry[-1][0]
                if ip_address not in resolved_servers:
                    resolved_servers.append(ip_address)

            if not resolved_servers:
                self.log.error(f"NTP DNS lookup returned no IPv4 addresses for {self.ntp_host}")
                return False

            self.ntp_servers = resolved_servers
            self.ntp_server_index = 0
            self.ntp_address = (self.ntp_servers[0], self.ntp_port)
            self.log.info(f"Resolved NTP host {self.ntp_host} to {self.ntp_servers}")
            return True
        except Exception as e:
            self.log.error(f"NTP DNS lookup failed for {self.ntp_host}: {e}")
            return False

    def configure_wifi(self) -> None:
        self.wlan = network.WLAN(network.STA_IF)
        self.wlan.active(True)
        self.wlan.config(pm=self.disable_power_management)
        self.mac = self.get_mac_address()
        self.mac_no_colons = self.mac.replace(":", "")
        self.hostname = self.determine_hostname()
        network.hostname(self.hostname)
    
    def set_ntp_sync_callback(self, callback) -> None:
        """
        Set a callback function to be called when an NTP sync occurs.
        The callback should accept a single argument which will be a tuple with values (year, month, day, hour, minute, second, dayofweek, dayofyear).
        """
        self.on_time_sync = callback

    def get_mac_address(self) -> str:
        """
        Get the MAC address of the wireless interface.
        Returns:
            str: The MAC address in the format 'xx:xx:xx:xx:xx:xx'.
        """
        mac = hexlify(self.wlan.config('mac'),':').decode()
        self.log.info(f"MAC address: {mac}")
        return mac

    def determine_hostname(self) -> str:
        """
        Generate and return a default hostname based on the MAC address if no
        custom hostname is provided.
        """
        if config.CUSTOM_HOSTNAME:
            hostname = config.CUSTOM_HOSTNAME
        else:
            hostname = "smibhid-" + self.mac_no_colons[-6:]
        self.log.info(f"Setting hostname to {hostname}")
        return hostname

    def startup(self) -> None:
        self.log.info("Starting wifi network monitor")
        create_task(self.network_monitor())

    def dump_status(self):
        status = self.wlan.status()
        self.log.info(f"active: {1 if self.wlan.active() else 0}, status: {status} ({self.status_names[status]})")
        return status
    
    async def wait_status(self, expected_status, *, timeout=config.WIFI_CONNECT_TIMEOUT_SECONDS, tick_sleep=0.5) -> bool:
        for unused in range(ceil(timeout / tick_sleep)):
            await sleep(tick_sleep)
            status = self.dump_status()
            if status == expected_status:
                return True
            elif status == self.CYW43_LINK_BADAUTH:
                self.log.error("Bad authentication, check your SSID and password")
                raise ValueError(self.status_names[status])
            elif status == self.CYW43_LINK_FAIL or status == self.CYW43_LINK_NONET:
                self.log.error(f"Connection failed: {self.status_names[status]}")
                raise Exception(self.status_names[status])
        return False
    
    async def disconnect_wifi_if_necessary(self) -> None:
        status = self.dump_status()
        if status >= self.CYW43_LINK_JOIN and status <= self.CYW43_LINK_UP:
            self.log.info("Disconnecting...")
            self.wlan.disconnect()
            try:
                await self.wait_status(self.CYW43_LINK_DOWN)
            except Exception as x:
                raise Exception(f"Failed to disconnect: {x}")
        self.log.info("Ready for connection!")
    
    def generate_connection_info(self, elapsed_ms=None) -> None:
        self.ip, self.subnet, self.gateway, self.dns = self.wlan.ifconfig()
        self.log.info(f"IP: {self.ip}, Subnet: {self.subnet}, Gateway: {self.gateway}, DNS: {self.dns}")

        if elapsed_ms is not None:
            self.log.info(f"Elapsed: {elapsed_ms}ms")
            if elapsed_ms > 5000:
                self.log.warn(f"took {elapsed_ms} milliseconds to connect to wifi")

    def has_valid_network_config(self) -> bool:
        ip, _, _, dns = self.wlan.ifconfig()
        return ip not in ("0.0.0.0", "Unknown") and dns not in ("0.0.0.0", "Unknown")

    async def wait_for_dhcp(self, *, timeout=config.WIFI_CONNECT_TIMEOUT_SECONDS, tick_sleep=0.5) -> bool:
        for unused in range(ceil(timeout / tick_sleep)):
            if self.has_valid_network_config():
                return True
            await sleep(tick_sleep)
        return False

    async def auth_error(self) -> None:
        self.log.info("Bad wifi credentials")
        await self.status_led.async_flash(2, 2)
    
    async def connection_error(self) -> None:
        self.log.info("Error connecting")
        await self.status_led.async_flash(2, 2)

    async def connection_success(self) -> None:
        self.log.info("Successful connection")
        await self.status_led.async_flash(1, 2)

    async def attempt_ap_connect(self) -> None:
        self.log.info(f"Connecting to SSID {self.wifi_ssid} (password: {self.wifi_password})...")
        await self.disconnect_wifi_if_necessary()
        self.wlan.connect(self.wifi_ssid, self.wifi_password)
        try:
            await self.wait_status(self.CYW43_LINK_UP)
            if not await self.wait_for_dhcp():
                raise Exception("Connected to wifi but DHCP/IP config not ready")
        except ValueError as ve:
            self.log.error(f"Authentication failed connecting to SSID {self.wifi_ssid}: {ve}")
            await self.auth_error()
            raise ValueError(f"Authentication failed connecting to SSID {self.wifi_ssid}: {ve}")
        except Exception as x:
            await self.connection_error()
            raise Exception(f"Failed to connect to SSID {self.wifi_ssid}: {x}")
        await self.connection_success()
        self.log.info("Connected successfully!")
    
    async def connect_wifi(self) -> None:
        self.log.info("Connecting to wifi")
        start_ms = ticks_ms()
        try:
            await self.attempt_ap_connect()
        except ValueError as ve:
            self.log.error(f"Auth error: {ve}")
            raise ValueError(ve)
        except Exception as e:
            raise Exception(f"Failed to connect to network: {e}")

        elapsed_ms = ticks_diff(ticks_ms(), start_ms)
        self.generate_connection_info(elapsed_ms)
        if not self.ntp_servers:
            self.refresh_ntp_servers()

    def get_status(self) -> int:
        return self.wlan.status()
    
    async def network_retry_backoff(self) -> None:
        self.log.info(f"Backing off retry for {config.WIFI_RETRY_BACKOFF_SECONDS} seconds")
        await self.status_led.async_flash((config.WIFI_RETRY_BACKOFF_SECONDS * self.led_retry_backoff_frequency), self.led_retry_backoff_frequency)

    async def check_network_access(self) -> bool:
        """
        Check and ensure network access by attempting to connect to the wifi network.
        Implements retry logic based on configuration settings.
        Returns:
            bool: True if network access is established, False otherwise.
        Raises a value error if the authentication fails.
        """
        if self.network_check_in_progress:
            self.log.info("Network access check already in progress, skipping")
            return False
        self.network_check_in_progress = True
        try:
            self.log.info("Checking for network access")
            retries = 0
            while (self.get_status() != 3 or not self.has_valid_network_config()) and retries <= config.WIFI_CONNECT_RETRIES:
                try:
                    await self.connect_wifi()
                    return True
                except ValueError as ve:
                    self.log.error(f"Auth error, will not retry, please check credentials in the config file : {ve}")
                    raise ValueError(ve)
                except Exception as e:
                    self.log.warn(f"Error connecting to wifi on attempt {retries + 1} of {config.WIFI_CONNECT_RETRIES + 1}: {e}")
                    retries += 1
                    if retries > config.WIFI_CONNECT_RETRIES:
                        self.log.error("Exceeded maximum wifi connection retries")
                        break
                    await self.network_retry_backoff()

            if self.get_status() == 3 and self.has_valid_network_config():
                self.log.info("Connected to wireless network")
                return True
            else:
                self.log.warn("Unable to connect to wireless network with valid DHCP config")
                return False
        finally:
            self.network_check_in_progress = False

    def check_ntp_sync_needed(self) -> bool:
        """
        Determine whether an NTP time synchronisation should be performed.

        This inspects ``ntp_last_synced_timestamp`` and
        ``NTP_SYNC_INTERVAL_SECONDS`` to decide if an NTP sync is due.

        Returns:
            bool: ``True`` if an NTP sync should be triggered, ``False``
            otherwise.
        """
        if self.ntp_last_synced_timestamp == 0:
            self.log.info("NTP sync needed: never synced before")
            return True
        elif (time() - self.ntp_last_synced_timestamp) > self.NTP_SYNC_INTERVAL_SECONDS:
            self.log.info(f"NTP sync needed: interval {self.NTP_SYNC_INTERVAL_SECONDS} exceeded")
            return True
        else:
            self.log.info("NTP sync not needed")
            return False

    async def network_monitor(self) -> None:
        self.log.info("Starting network monitor")
        while True:
            status = self.get_status()
            config_valid = self.has_valid_network_config()

            network_state = (status, config_valid)
            if network_state != self.last_network_state:
                self.last_network_state = network_state
                status_desc = self.status_names.get(status, "Unknown status")
                if status == self.CYW43_LINK_UP and config_valid:
                    self.generate_connection_info()
                    self.log.info("WiFi connected with valid DHCP configuration")
                    self.log.info(f"WiFi status transition: {status} ({status_desc})")
                else:
                    self.log.warn(f"WiFi not ready: status {status} ({status_desc}), dhcp_valid={config_valid}")

            if (status != self.CYW43_LINK_UP or not config_valid):
                if not self.network_check_in_progress:
                    self.log.info("Network not ready, scheduling connectivity check")
                    create_task(self.check_network_access())
                else:
                    self.log.info("Network access check already in progress")

            if self.check_ntp_sync_needed():
                if not self.ntp_sync_in_progress:
                    self.log.info("Scheduling NTP sync from network monitor")
                    create_task(self.async_sync_rtc_from_ntp())
                else:
                    self.log.info("NTP sync already in progress")
            await sleep(5)
    
    def get_mac(self) -> str:
        """
        Get the MAC address of the wireless interface as stored in the Wireless
        Network class - cheaper than calling the wlan config.
        """
        return self.mac
    
    def get_ip(self) -> str:
        return self.ip
    
    def get_wlan_status_description(self, status) -> str:
        description = self.status_names[status]
        return description
    
    def get_all_data(self) -> dict:
        all_data = {}
        all_data['mac'] = self.get_mac()
        status = self.get_status()
        all_data['status description'] = self.get_wlan_status_description(status)
        all_data['status code'] = status
        return all_data

    def get_hostname(self) -> str:
        return self.hostname
    
    async def async_get_timestamp_from_ntp(self, allow_dns_refresh_retry=True):
        buf_size = 48
        ntp_request_id = 0x1b

        gc.collect()
        query = bytearray(buf_size)
        query[0] = ntp_request_id

        if not self.has_valid_network_config():
            self.log.warn("NTP skipped: network lacks DHCP IP/DNS configuration")
            return None

        if not self.ntp_servers and not self.refresh_ntp_servers():
            return None

        server_count = len(self.ntp_servers)
        if server_count == 0:
            self.log.error("No NTP servers available after DNS resolution")
            return None

        for attempt in range(server_count):
            server_index = (self.ntp_server_index + attempt) % server_count
            ntp_host = self.ntp_servers[server_index]
            timestamp = None
            udp_socket = None

            try:
                udp_socket = socket(AF_INET, SOCK_DGRAM)
                udp_socket.setblocking(False)
                udp_socket.sendto(query, (ntp_host, self.ntp_port))

                timeout_ms = 5000
                start_time = ticks_ms()
                while ticks_diff(ticks_ms(), start_time) < timeout_ms:
                    try:
                        data, _ = udp_socket.recvfrom(buf_size)

                        local_epoch = 2208988800
                        timestamp = struct.unpack("!I", data[40:44])[0] - local_epoch
                        timestamp = gmtime(timestamp)
                        break
                    except OSError:
                        await sleep(0.1)

                if timestamp is not None:
                    self.ntp_server_index = server_index
                    self.ntp_address = (ntp_host, self.ntp_port)
                    if attempt > 0:
                        self.log.info(f"NTP fallback succeeded using {ntp_host}")
                    return timestamp

                self.log.warn(f"No NTP response from {ntp_host} within timeout")
            except OSError as e:
                if e.args and e.args[0] == 12:
                    gc.collect()
                self.log.error(f"Failed to get NTP time from {ntp_host}: {e}")
            except Exception as e:
                self.log.error(f"Failed to get NTP time from {ntp_host}: {e}")
            finally:
                if udp_socket:
                    try:
                        udp_socket.close()
                    except Exception:
                        pass

                gc.collect()

            if attempt < (server_count - 1):
                next_host = self.ntp_servers[(server_index + 1) % server_count]
                self.log.warn(f"Trying fallback NTP server {next_host}")

        if allow_dns_refresh_retry:
            self.log.warn("All cached NTP servers failed, refreshing DNS and retrying once")
            if self.refresh_ntp_servers():
                return await self.async_get_timestamp_from_ntp(allow_dns_refresh_retry=False)

        return None

    async def async_sync_rtc_from_ntp(self) -> bool:
        result = False
        if self.ntp_sync_in_progress:
            self.log.info("NTP sync already in progress, skipping")
            return False

        self.ntp_sync_in_progress = True
        try:
            if self.get_status() != self.CYW43_LINK_UP or not self.has_valid_network_config():
                self.ntp_sync_status = False
                self.log.error("No network access, cannot sync RTC from NTP")
                if not self.network_check_in_progress:
                    self.log.info("Scheduling connectivity check after NTP sync skip")
                    create_task(self.check_network_access())
                return False

            timestamp = await self.async_get_timestamp_from_ntp()
            self.log.info(f"NTP timestamp obtained: {timestamp}")
            if timestamp is None:
                self.ntp_sync_status = False
                self.log.error("NTP sync failed, RTC not updated")
                return False

            RTC().datetime((
                timestamp[0], timestamp[1], timestamp[2], timestamp[6], 
                timestamp[3], timestamp[4], timestamp[5], 0))
            
            # Call time sync callback if registered
            if self.on_time_sync:
                try:
                    self.on_time_sync(timestamp)
                except Exception as e:
                    self.log.error(f"Error in time sync callback: {e}")

            self.ntp_last_synced_timestamp = time()
            self.ntp_sync_status = True
            self.prtc_sync_status = True
            self.log.info("RTC synced from NTP")
            result = True
        except Exception as e:
            self.ntp_sync_status = False
            self.log.error(f"Failed to sync RTC from NTP: {e}")
        finally:
            self.ntp_sync_in_progress = False
        return result
    
    def is_connected(self) -> bool:
        """
        Determines if the wifi connection is connected and has an IP address.
        Returns:
            bool: True if connected with IP, False otherwise.
        """
        return self.get_status() == 3

    def get_ntp_sync_status(self) -> bool:
        """
        Returns the current NTP sync status.
        Returns:
            bool: True if last NTP sync was successful, False otherwise.
        """        
        return self.ntp_sync_status
    
    def get_prtc_sync_status(self) -> bool:
        """
        Returns the current PRTC sync status.
        Returns:
            bool: True if last PRTC sync was successful, False otherwise.
        """
        return self.prtc_sync_status
