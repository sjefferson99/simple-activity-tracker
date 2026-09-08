from machine import Pin, SPI
from config import (
    DISPLAY_SPI_ID,
    DISPLAY_SCK_PIN,
    DISPLAY_MOSI_PIN,
    DISPLAY_CS_PIN,
    DISPLAY_DC_PIN,
    DISPLAY_RST_PIN,
    DISPLAY_BL_PIN,
    DISPLAY_SPI_BAUDRATE,
    DISPLAY_WIDTH,
    DISPLAY_HEIGHT,
)
from lib.ulogging import uLogger
import lib.st7789py as st7789
import lib.vga1_8x16 as font


class Display:

    def __init__(self) -> None:
        """
        Display driver for a Waveshare 2.4inch LCD Module (ST7789 controller,
        4-wire SPI), used to show simple status text such as the current GPS fix.
        """
        self.log = uLogger("Display")
        spi = SPI(
            DISPLAY_SPI_ID,
            baudrate=DISPLAY_SPI_BAUDRATE,
            sck=Pin(DISPLAY_SCK_PIN),
            mosi=Pin(DISPLAY_MOSI_PIN),
        )
        self.tft = st7789.ST7789(
            spi,
            DISPLAY_WIDTH,
            DISPLAY_HEIGHT,
            reset=Pin(DISPLAY_RST_PIN, Pin.OUT),
            dc=Pin(DISPLAY_DC_PIN, Pin.OUT),
            cs=Pin(DISPLAY_CS_PIN, Pin.OUT),
            backlight=Pin(DISPLAY_BL_PIN, Pin.OUT),
        )
        self.font = font
        self.log.info(f"Display configured: {DISPLAY_WIDTH}x{DISPLAY_HEIGHT} on SPI{DISPLAY_SPI_ID}")

    def show_text_line(self, text: str, fg=st7789.WHITE, bg=st7789.BLACK) -> None:
        """
        Clear the display and show a single line of text at the top left.
        Intended for simple status output such as "Fix: <fix info>".
        """
        self.tft.fill(bg)
        self.tft.text(self.font, text, 0, 0, fg, bg)
