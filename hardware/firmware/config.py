## Logging
# Level 0-4: 0 = Disabled, 1 = Critical, 2 = Error, 3 = Warning, 4 = Info
LOG_LEVEL = 2
# Handlers: Populate list with zero or more of the following log output handlers (case sensitive): "Console", "File"
#LOG_HANDLERS = ["Console"]
LOG_HANDLERS = ["File"]
#LOG_HANDLERS = ["Console", "File"]
# Max log file size in bytes, there will be a maximum of 2 files at this size created
LOG_FILE_MAX_SIZE = 10240

## WIFI
WIFI_SSID = ""
WIFI_PASSWORD = ""
WIFI_COUNTRY = "GB"
WIFI_CONNECT_TIMEOUT_SECONDS = 10
WIFI_CONNECT_RETRIES = 1
WIFI_RETRY_BACKOFF_SECONDS = 5
# Leave as none for MAC based unique hostname or specify a custom hostname string
CUSTOM_HOSTNAME = "Pico-Tracker"

# Set your custom timezone in IANA format (see https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)
TIMEZONE = "Etc/UTC"

## NTP poll frequency - Minimum period is every 60 seconds to avoid NTP server blacklisting
NTP_SYNC_INTERVAL_SECONDS = 3600

## I2C
SDA_PIN = 0
SCL_PIN = 1
I2C_ID = 0
I2C_FREQ = 400000

## GPS (PA1616S, NMEA-0183 over UART)
GPS_UART_ID = 0
GPS_TX_PIN = 16
GPS_RX_PIN = 17
# PA1616S default baud rate
GPS_UART_BAUD = 9600

## Display (Waveshare 2.4inch LCD Module, ST7789, 4-wire SPI)
# Wired by hand (not a plug-on Pico board) - update these to match actual wiring
DISPLAY_SPI_ID = 0
DISPLAY_SCK_PIN = 2
DISPLAY_MOSI_PIN = 3
DISPLAY_CS_PIN = 1
DISPLAY_DC_PIN = 21
DISPLAY_RST_PIN = 20
DISPLAY_BL_PIN = 19
DISPLAY_SPI_BAUDRATE = 40000000
DISPLAY_WIDTH = 240
DISPLAY_HEIGHT = 320

## Overclocking - Pico1 default 133MHz, Pico2 default 150MHz
CLOCK_FREQUENCY = 133000000
