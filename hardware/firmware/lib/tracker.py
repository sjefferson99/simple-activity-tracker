from lib.ulogging import uLogger
from lib.networking import WirelessNetwork
from lib.gps import Gps
from machine import freq, I2C
from config import CLOCK_FREQUENCY, I2C_ID, SDA_PIN, SCL_PIN, I2C_FREQ, TIMEZONE
from asyncio import sleep_ms, create_task, get_event_loop, Event
from lib.button import Button
from lib.utimezone import TimeZone

class Tracker:
    
    def __init__(self) -> None:
        """
        Tracker device for displaying activity information on connected
        displays and syncing activity information to the SAT server.
        """
        self.log = uLogger("Tracker")
        self.log.warn("Pico-Tracker has been restarted")
        self.version = "0.0.1"
        self.log.info("Setting CPU frequency to: " + str(CLOCK_FREQUENCY / 1000000) + "MHz")
        freq(CLOCK_FREQUENCY)
        self.i2c = I2C(I2C_ID, sda = SDA_PIN, scl = SCL_PIN, freq = I2C_FREQ)
        self.wifi = WirelessNetwork()
        self.gps = Gps()

    def startup(self) -> None:
        """
        Start the tracker device, including connecting to WiFi and starting the main event loop.
        """
        self.log.info("Starting Pico-Tracker version: " + self.version)
        #self.wifi.startup() #TODO add networking mode for devices that are often away from wifi and will retry on button rather than constant polling for power saving
        self.timezone = TimeZone(TIMEZONE)
        self.log.info("Timezone set to: " + TIMEZONE)
        create_task(self.gps.async_poll_loop())
        create_task(self.async_main_loop())
        self.loop = get_event_loop()
        self.loop.run_forever()

    async def async_main_loop(self) -> None:
        """
        Main event loop for the tracker device. This loop will run indefinitely, handling events and updating displays.
        """
        self.log.info("Entering main event loop")
        while True:
            if self.gps.has_recent_fix():
                self.log.info(f"GPS fix: {self.gps.get_fix()}")
            else:
                self.log.info("GPS: no recent fix")
            await sleep_ms(1000)
