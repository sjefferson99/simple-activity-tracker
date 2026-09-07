from machine import UART
from asyncio import sleep_ms
from utime import ticks_ms, ticks_diff
from config import GPS_UART_ID, GPS_TX_PIN, GPS_RX_PIN, GPS_UART_BAUD
from lib.ulogging import uLogger
from lib.micropyGPS import MicropyGPS

# A fix is considered stale if no valid fix sentence has been parsed within this window
FIX_EXPIRY_MS = 3000


class Gps:

    def __init__(self) -> None:
        """
        GPS reader for a PA1616S (or other NMEA-0183) module attached over UART.
        Feeds raw NMEA sentences into a MicropyGPS parser and exposes the
        latest fix as plain attributes.
        """
        self.log = uLogger("GPS")
        self.parser = MicropyGPS(location_formatting='dd')
        self.uart = UART(
            GPS_UART_ID,
            baudrate=GPS_UART_BAUD,
            tx=GPS_TX_PIN,
            rx=GPS_RX_PIN,
        )
        self.last_valid_fix_ms = None
        self.log.info(f"GPS UART{GPS_UART_ID} configured on tx={GPS_TX_PIN}, rx={GPS_RX_PIN}, baud={GPS_UART_BAUD}")

    def read(self) -> None:
        """
        Read and parse any NMEA data currently waiting in the UART buffer.
        Non-blocking: does nothing if no data is available.
        """
        data = self.uart.read()
        if not data:
            return
        for byte in data:
            try:
                sentence_type = self.parser.update(chr(byte))
            except ValueError as e:
                self.log.warn(f"Discarding malformed NMEA data: {e}")
                continue
            if sentence_type is not None and self.parser.valid:
                self.last_valid_fix_ms = ticks_ms()

    async def async_poll_loop(self, interval_ms: int = 100) -> None:
        """
        Continuously read and parse incoming NMEA data at the given interval.
        Intended to be run as its own asyncio task for the lifetime of the device.
        """
        self.log.info("Starting GPS poll loop")
        while True:
            self.read()
            await sleep_ms(interval_ms)

    def has_fix(self) -> bool:
        """
        Returns True if the most recently parsed sentence reported a valid fix.
        Note this flag does not expire on its own if the GPS stops sending data -
        use has_recent_fix() to also require the fix to be recent.
        """
        return self.parser.valid

    def has_recent_fix(self) -> bool:
        """
        Returns True if a valid fix was parsed within the last FIX_EXPIRY_MS
        milliseconds. Use this over has_fix() to detect a GPS that has stopped
        sending data or lost its fix, since has_fix() alone never expires.
        """
        if self.last_valid_fix_ms is None:
            return False
        return ticks_diff(ticks_ms(), self.last_valid_fix_ms) <= FIX_EXPIRY_MS

    def get_fix(self) -> dict:
        """
        Returns the latest parsed fix as a plain dict:
        latitude/longitude in decimal degrees (signed, +N/+E), altitude in
        metres, speed in km/h, course in degrees, satellite count, and
        whether the fix is currently valid.
        """
        latitude, lat_hemi = self.parser.latitude
        longitude, lon_hemi = self.parser.longitude
        if lat_hemi == 'S':
            latitude = -latitude
        if lon_hemi == 'W':
            longitude = -longitude

        return {
            "valid": self.parser.valid,
            "latitude": latitude,
            "longitude": longitude,
            "altitude_m": self.parser.altitude,
            "speed_kmh": self.parser.speed[2],
            "course_deg": self.parser.course,
            "satellites_in_use": self.parser.satellites_in_use,
        }
