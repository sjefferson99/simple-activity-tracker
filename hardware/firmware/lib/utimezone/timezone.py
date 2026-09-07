# utimezone
# Licence: MIT
# Repo: samcorky/utimezone

import re

from .transition_rule import _TransitionRule
from .utils import (
    datetime_to_epoch,
    epoch_to_utc_year,
    epoch_to_ymdhms,
    format_iso8601,
    parse_signed_hms_to_seconds,
)

# Keep the code MicroPython-friendly: public methods accept (y, m, d, h, mi, s) tuples

_POSIX_TZ_RE: re.Pattern = re.compile(
    r"^(<[^>]+>|[A-Za-z]+)([+-]?[0-9]+(:[0-9]+(:[0-9]+)?)?)((<[^>]+>|[A-Za-z]+)([+-]?[0-9]+(:[0-9]+(:[0-9]+)?)?)?)?(,([^,]+),([^,]+))?$"
)


class TimeZone:
    """Represent a lightweight timezone rule set derived from IANA/POSIX definitions.

    The object exposes a small, portable public API that operates primarily on
    epoch seconds or plain (year, month, day, hour, minute, second) tuples so
    it remains friendly to MicroPython and other constrained environments.
    """

    DEFAULT_TIMEZONE = "Etc/Zulu"

    iana_timezone_name: str | None
    _posix_timezone_string: str

    _std_offset: int
    _std_tz_name: str | None

    _has_dst: bool
    _dst_tz_name: str | None
    _dst_offset: int | None

    _dst_start_rule: _TransitionRule | None
    _dst_end_rule: _TransitionRule | None

    _cache_year: int | None
    _cache_dst_start: int | None
    _cache_dst_end: int | None

    def __init__(self, iana_timezone_name: str | None = None) -> None:
        """Create a TimeZone from a known IANA timezone name.

        Args:
            iana_timezone_name: a key present in the embedded database.
                If None, you MUST use from_posix_timezone_string instead.

        Raises:
            ValueError: if the provided IANA name is not known.
        """
        self._init_state()

        if iana_timezone_name is None:
            # from_posix_timezone_string will set up the rest
            return

        from . import db

        self.iana_timezone_name = iana_timezone_name
        posix_rule = db.get_posix_rule_for_iana_name(iana_timezone_name)
        if posix_rule is None:
            raise ValueError(f"Unknown IANA timezone name: {iana_timezone_name}")

        self._posix_timezone_string = posix_rule
        del posix_rule
        del db

        self._parse_posix_timezone_string()

    # Public API uses tuple-based datetime inputs for MicroPython compatibility.

    @classmethod
    def from_posix_timezone_string(cls, posix_timezone_string: str) -> "TimeZone":
        """Create a TimeZone from a POSIX timezone string.

        This is useful for constructing custom or lightweight timezone definitions
        without relying on an IANA name. This is particularly efficient on MicroPython
        as it skips the IANA-to-POSIX lookup.

        Args:
            posix_timezone_string: a POSIX TZ string. Example:
                "EST5EDT,M3.2.0,M11.1.0".
        """
        tz = cls(None)
        tz._posix_timezone_string = posix_timezone_string
        tz._parse_posix_timezone_string()
        return tz

    def _init_state(self) -> None:
        self.iana_timezone_name = None
        self._posix_timezone_string = ""

        self._std_offset = 0
        self._std_tz_name = None

        self._has_dst = False
        self._dst_tz_name = None
        self._dst_offset = None

        self._dst_start_rule = None
        self._dst_end_rule = None

        self._cache_year = None
        self._cache_dst_start = None
        self._cache_dst_end = None

    def _parse_posix_timezone_string(self) -> None:
        s: str = self._posix_timezone_string.strip()

        m = re.match(_POSIX_TZ_RE, s)
        if m is None:
            raise ValueError(f"Invalid POSIX timezone string: {s}")

        # Extract groups: std_name, std_off, dst_name, dst_off, start, end
        std_name, std_off = m.group(1), m.group(2)
        dst_name, dst_off = m.group(6), m.group(7)
        start, end = m.group(11), m.group(12)

        self._std_tz_name = std_name
        self._std_offset = -parse_signed_hms_to_seconds(std_off)

        if dst_name is None:
            self._init_fixed_offset()
        else:
            self._init_dst_offset(dst_name, dst_off)
            self._init_dst_rules(start, end)

    def _init_fixed_offset(self) -> None:
        self._has_dst = False
        self._dst_tz_name = None
        self._dst_offset = None
        self._dst_start_rule = None
        self._dst_end_rule = None

    def _init_dst_offset(self, dst_name: str, dst_off: str | None) -> None:
        self._has_dst = True
        self._dst_tz_name = dst_name
        if dst_off is None:
            self._dst_offset = self._std_offset + 3600
        else:
            self._dst_offset = -parse_signed_hms_to_seconds(dst_off)

    def _init_dst_rules(self, start: str | None, end: str | None) -> None:
        self._dst_start_rule = (
            _TransitionRule(start, self._std_offset) if start is not None else None
        )
        self._dst_end_rule = (
            _TransitionRule(end, self._dst_offset) if end is not None else None
        )

    def _ensure_cache(self, year: int) -> None:
        if not self._has_dst:
            self._cache_year = year
            self._cache_dst_start = None
            self._cache_dst_end = None
            return

        if self._cache_year == year:
            return

        if self._dst_start_rule is None or self._dst_end_rule is None:
            raise ValueError(
                f"Incomplete DST rules for timezone: {self.iana_timezone_name}"
            )

        self._cache_year = year
        self._cache_dst_start = self._dst_start_rule.get_transition(year)
        self._cache_dst_end = self._dst_end_rule.get_transition(year)

    def _get_datetime_components(self, dt, *args):
        if isinstance(dt, (tuple, list)):
            if len(dt) < 3:
                raise ValueError(
                    "datetime tuple must have at least 3 elements (y, m, d)"
                )
            y, mo, d = dt[0], dt[1], dt[2]
            h = dt[3] if len(dt) > 3 else 0
            mi = dt[4] if len(dt) > 4 else 0
            s = dt[5] if len(dt) > 5 else 0
            return y, mo, d, h, mi, s

        if len(args) >= 2:
            y = dt
            mo = args[0]
            d = args[1]
            h = args[2] if len(args) > 2 else 0
            mi = args[3] if len(args) > 3 else 0
            s = args[4] if len(args) > 4 else 0
            return y, mo, d, h, mi, s

        return epoch_to_ymdhms(int(dt))

    def is_dst(self, epoch_seconds: int) -> bool:
        """Return True if the given UTC epoch (seconds) falls in DST for this zone.

        Args:
            epoch_seconds: seconds since 1970-01-01 00:00:00 UTC.

        Returns:
            True when DST rules apply at the given UTC instant, False otherwise.
        """
        if not self._has_dst:
            return False

        year = epoch_to_utc_year(epoch_seconds)
        self._ensure_cache(year)

        if self._cache_dst_start < self._cache_dst_end:
            return self._cache_dst_start <= epoch_seconds < self._cache_dst_end

        # Southern Hemisphere style: DST season crosses the new year boundary.
        return (
            epoch_seconds >= self._cache_dst_start
            or epoch_seconds < self._cache_dst_end
        )

    def is_dst_at(
        self,
        dt: tuple[int, int, int, int, int, int] | int,
        *args: int,
    ) -> bool:
        """Return whether the given local date/time is in DST."""
        y, mo, d, h, mi, s = self._get_datetime_components(dt, *args)
        epoch_seconds = datetime_to_epoch(y, mo, d, h, mi, s)
        return self.is_dst(epoch_seconds)

    def offset_at(
        self,
        dt: tuple[int, int, int, int, int, int] | int,
        *args: int,
    ) -> int:
        """Return the active UTC->local offset (seconds) for a given local date/time."""
        y, mo, d, h, mi, s = self._get_datetime_components(dt, *args)

        if self.is_dst_at(y, mo, d, h, mi, s):
            return self._dst_offset
        return self._std_offset

    def name_at(
        self,
        dt: tuple[int, int, int, int, int, int] | int,
        *args: int,
    ) -> str | None:
        """Return the active timezone abbreviation for a given local date/time."""
        y, mo, d, h, mi, s = self._get_datetime_components(dt, *args)

        if self.is_dst_at(y, mo, d, h, mi, s):
            return self._dst_tz_name
        return self._std_tz_name

    def offset_for_epoch(self, epoch_seconds: int) -> int:
        """Return the active UTC->local offset (seconds) for a UTC epoch."""
        return self._dst_offset if self.is_dst(epoch_seconds) else self._std_offset

    def name_for_epoch(self, epoch_seconds: int) -> str | None:
        """Return the active timezone abbreviation for a UTC epoch."""
        return self._dst_tz_name if self.is_dst(epoch_seconds) else self._std_tz_name

    def utc_epoch_to_local(
        self, epoch_seconds: int
    ) -> tuple[int, int, int, int, int, int]:
        """Convert a UTC epoch to local (y, m, d, h, mi, s)."""
        offset = self.offset_for_epoch(epoch_seconds)
        local_epoch = epoch_seconds + offset
        return epoch_to_ymdhms(int(local_epoch))

    def utc_datetime_to_local(
        self, dt: tuple[int, int, int, int, int, int] | int, *args: int
    ) -> tuple[int, int, int, int, int, int]:
        """Convert a UTC datetime to local."""
        y, mo, d, h, mi, s = self._get_datetime_components(dt, *args)
        epoch = datetime_to_epoch(y, mo, d, h, mi, s)
        return self.utc_epoch_to_local(epoch)

    def local_datetime_to_utc(
        self,
        dt: tuple[int, int, int, int, int, int] | int,
        *args: int,
        fold: bool = False,
    ) -> tuple[int, int, int, int, int, int]:
        """Convert a local naive datetime to a UTC datetime tuple."""
        actual_fold = fold
        if len(args) == 6:
            actual_fold = bool(args[5])
            args = args[:5]

        year, month, day, hour, minute, second = self._get_datetime_components(
            dt, *args
        )
        utc_epoch = self.local_to_utc_epoch(
            year, month, day, hour, minute, second, fold=actual_fold
        )
        return epoch_to_ymdhms(int(utc_epoch))

    def local_to_utc_epoch(
        self,
        dt: tuple[int, int, int, int, int, int] | int,
        *args: int,
        fold: bool = False,
    ) -> int:
        """Resolve a local naive date/time to a UTC epoch.

        `fold=False` (default) returns earlier instant, `fold=True` returns later.
        """
        actual_fold = fold

        if len(args) == 6:
            actual_fold = bool(args[5])
            args = args[:5]

        year, month, day, hour, minute, second = self._get_datetime_components(
            dt, *args
        )
        naive_epoch = datetime_to_epoch(year, month, day, hour, minute, second)

        candidates = self._get_utc_candidates(naive_epoch)
        valid = [c for c in candidates if self._is_valid_candidate(c, naive_epoch)]

        if len(valid) == 1:
            return valid[0]

        if len(valid) > 1:
            valid.sort()
            return valid[1] if actual_fold else valid[0]

        return int(naive_epoch) - self._std_offset

    def to_iso8601(
        self,
        dt: tuple[int, int, int, int, int, int] | int,
        *args: int,
        is_local: bool = False,
    ) -> str:
        """Return an ISO 8601 formatted string (e.g., 2026-04-16T13:41:00+01:00).

        If `is_local=False` (default), `dt` is treated as a UTC datetime/epoch.
        If `is_local=True`, `dt` is treated as a local datetime/epoch (already
        containing the timezone's offset).
        """
        actual_is_local = is_local
        if len(args) == 6:
            actual_is_local = bool(args[5])
            args = args[:5]

        y, mo, d, h, mi, s = self._get_datetime_components(dt, *args)

        if not actual_is_local:
            epoch = datetime_to_epoch(y, mo, d, h, mi, s)
            offset = self.offset_for_epoch(epoch)
            y, mo, d, h, mi, s = self.utc_epoch_to_local(epoch)
        else:
            offset = self.offset_at(y, mo, d, h, mi, s)

        return format_iso8601(y, mo, d, h, mi, s, offset)

    def _get_utc_candidates(self, naive_epoch: int) -> list[int]:
        """Return potential UTC instants for a naive local epoch."""
        candidates: list[int] = [int(naive_epoch) - self._std_offset]

        if self._has_dst and self._dst_offset is not None:
            dst_candidate = int(naive_epoch) - self._dst_offset
            if dst_candidate not in candidates:
                candidates.append(dst_candidate)

        return candidates

    def _is_valid_candidate(self, candidate_epoch: int, naive_epoch: int) -> bool:
        """Check if a UTC candidate instant maps back to the correct local offset."""
        active_offset = self.offset_for_epoch(candidate_epoch)
        return int(naive_epoch) - active_offset == candidate_epoch

    def __repr__(self) -> str:
        if self.iana_timezone_name is not None:
            return f"<TimeZone {self.iana_timezone_name}>"
        return f"<TimeZone {self._posix_timezone_string}>"
