# utimezone
# Licence: MIT
# Repo: samcorky/utimezone
import re


def is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def days_in_month(year: int, month: int) -> int:
    if not 1 <= month <= 12:
        raise ValueError(f"Bad month: {month}")

    if month == 2:
        return 29 if is_leap_year(year) else 28

    if month in (4, 6, 9, 11):
        return 30

    return 31


def is_valid_date(year: int, month: int, day: int) -> bool:
    return 1 <= month <= 12 and 1 <= day <= days_in_month(year, month)


def day_of_week(year: int, month: int, day: int) -> int:
    """
    Zeller's Congruence for the Gregorian calendar.
    Returns 0=Sunday, 1=Monday, ..., 6=Saturday.
    """
    if month < 3:
        month += 12
        year -= 1

    k = year % 100
    j = year // 100

    h = (day + (13 * (month + 1)) // 5 + k + k // 4 + j // 4 + 5 * j) % 7

    # Zeller's returns 0=Saturday … 6=Friday, convert to Sunday=0
    return (h + 6) % 7


def day_of_year_to_month_day(year: int, day_of_year: int) -> tuple[int, int]:
    """Convert 1-indexed day-of-year to (month, day)."""
    if day_of_year < 1:
        raise ValueError(f"Bad day_of_year: {day_of_year}")
    month = 1

    while True:
        month_days = days_in_month(year, month)
        if day_of_year <= month_days:
            return month, day_of_year
        day_of_year -= month_days
        month += 1


def datetime_to_epoch(
    year: int, month: int, day: int, hour: int, minute: int, second: int
) -> int:
    y = year
    m = month

    if m <= 2:
        y -= 1
        m += 12

    era = y // 400
    yoe = y - era * 400
    doy = (153 * (m - 3) + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    days_since_epoch = era * 146097 + doe - 719468

    return days_since_epoch * 86400 + hour * 3600 + minute * 60 + second


def epoch_to_utc_year(epoch_seconds: int) -> int:
    year = 1970
    days_remaining = epoch_seconds // 86400

    if days_remaining < 0:
        # Move back in time
        while days_remaining < 0:
            year -= 1
            year_days = 366 if is_leap_year(year) else 365
            days_remaining += year_days
        return year

    # Move forward in time
    while True:
        year_days = 366 if is_leap_year(year) else 365
        if days_remaining < year_days:
            return year
        days_remaining -= year_days
        year += 1


def epoch_to_ymdhms(epoch_seconds: int) -> tuple[int, int, int, int, int, int]:
    """Convert an epoch to a UTC date/time tuple (y, m, d, h, mi, s)."""
    days = epoch_seconds // 86400
    seconds_in_day = epoch_seconds % 86400

    hour = seconds_in_day // 3600
    minute = (seconds_in_day % 3600) // 60
    second = seconds_in_day % 60

    # Invert the algorithm used in datetime_to_epoch
    # days_since_epoch = era * 146097 + doe - 719468
    d = days + 719468

    era = d // 146097
    doe = d - era * 146097  # day-of-era

    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = int(yoe) + era * 400

    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153

    day = doy - (153 * mp + 2) // 5 + 1
    month = mp + 3 if mp < 10 else mp - 9
    year = y + (0 if mp < 10 else 1)

    return year, month, day, hour, minute, second


_TIME_PART_RE = re.compile("^([+-])?([0-9]+)(:([0-9]+)(:([0-9]+))?)?$")


def parse_signed_hms_to_seconds(value: str) -> int:
    if value is None:
        raise ValueError("Value must be a string, not None")

    value = value.strip()
    if not value:
        raise ValueError("Value must not be empty")

    m = _TIME_PART_RE.match(value)
    if m is None:
        raise ValueError(f"Bad time value: {value!r}")

    sign_s = m.group(1)
    sign = -1 if sign_s == "-" else 1

    h = int(m.group(2))
    mm = int(m.group(4) or "0")
    ss = int(m.group(6) or "0")

    if mm >= 60 or ss >= 60:
        raise ValueError(f"Bad time value (minute/second out of range): {value!r}")

    return sign * (h * 3600 + mm * 60 + ss)


def format_iso8601(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: int,
    offset_seconds: int = 0,
) -> str:
    """Format a date/time and offset as an ISO 8601 string."""
    dt_str = f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}"

    if offset_seconds == 0:
        return f"{dt_str}Z"

    sign = "+" if offset_seconds >= 0 else "-"
    abs_offset = abs(offset_seconds)
    off_h = abs_offset // 3600
    off_m = (abs_offset % 3600) // 60

    return f"{dt_str}{sign}{off_h:02d}:{off_m:02d}"


def shift_date(year: int, month: int, day: int, day_shift: int) -> tuple[int, int, int]:
    """Shift a date by a number of days, correctly handling month/year boundaries."""
    day += day_shift

    while day < 1:
        month -= 1
        if month < 1:
            month = 12
            year -= 1
        day += days_in_month(year, month)

    while day > days_in_month(year, month):
        day -= days_in_month(year, month)
        month += 1
        if month > 12:
            month = 1
            year += 1

    return year, month, day
