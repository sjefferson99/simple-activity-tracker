# utimezone
# Licence: MIT
# Repo: samcorky/utimezone
import re  # type: ignore

from .utils import (
    datetime_to_epoch,
    day_of_week,
    day_of_year_to_month_day,
    days_in_month,
    is_leap_year,
    parse_signed_hms_to_seconds,
    shift_date,
)


class _TransitionRule:
    """MicroPython-friendly representation of a POSIX TZ rule.

    Supported forms: Mm.w.d[/time], Jn[/time], n[/time].
    """

    def __init__(self, posix_rule: str, transition_offset_seconds: int = 0) -> None:
        if posix_rule is None:
            raise ValueError("posix_rule must not be None")

        self.posix_rule: str = posix_rule.strip()
        if not self.posix_rule:
            raise ValueError("posix_rule must not be empty")

        self.rule_type: str = ""
        self.month: int = 0
        self.week: int = 0
        self.weekday: int = 0
        self.day: int = 0
        self.seconds: int = 0

        self.transition_offset_seconds = transition_offset_seconds
        self._parse_posix_rule()

    def _parse_posix_rule(self) -> None:
        """Parse POSIX rule forms (M, J, N). Default time is 02:00."""
        rule = self.posix_rule

        if rule.startswith("M"):
            self._parse_month_week_day_rule(rule)
            return

        if rule.startswith("J"):
            self._parse_julian_rule(rule)
            return

        self._parse_day_of_year_rule(rule)

    def _parse_month_week_day_rule(self, rule: str) -> None:
        m = re.match("^M([0-9]+)\\.([0-9]+)\\.([0-9]+)(/(.+))?$", rule)
        if m is None:
            raise ValueError(f"Unsupported DST rule: {rule!r}")

        self.rule_type = "M"
        self.month = int(m.group(1))
        self.week = int(m.group(2))
        self.weekday = int(m.group(3))

        self._validate_m_rule()
        self.seconds = self._parse_rule_time(m.group(5))

    def _validate_m_rule(self) -> None:
        if not (1 <= self.month <= 12):
            raise ValueError(f"Bad month: {self.month}")
        if not (1 <= self.week <= 5):
            raise ValueError(f"Bad week: {self.week}")
        if not (0 <= self.weekday <= 6):
            raise ValueError(f"Bad weekday: {self.weekday}")

    def _parse_julian_rule(self, rule: str) -> None:
        m = re.match("^J([0-9]+)(/(.+))?$", rule)
        if m is None:
            raise ValueError(f"Unsupported DST rule: {rule!r}")

        self.rule_type = "J"
        self.day = int(m.group(1))

        if not (1 <= self.day <= 365):
            raise ValueError(f"Bad Julian day: {self.day}")

        self.seconds = self._parse_rule_time(m.group(3))

    def _parse_day_of_year_rule(self, rule: str) -> None:
        m = re.match("^([0-9]+)(/(.+))?$", rule)
        if m is None:
            raise ValueError(f"Unsupported DST rule: {rule!r}")

        self.rule_type = "N"
        self.day = int(m.group(1))

        if not (0 <= self.day <= 365):
            raise ValueError(f"Bad day-of-year: {self.day}")

        self.seconds = self._parse_rule_time(m.group(3))

    @staticmethod
    def _parse_rule_time(time_s: str | None) -> int:
        return 2 * 3600 if time_s is None else parse_signed_hms_to_seconds(time_s)

    def _resolve_month_week_day_rule(self, year: int) -> tuple[int, int]:
        first_weekday = day_of_week(year, self.month, 1)
        days_total = days_in_month(year, self.month)

        first_match = 1 + (self.weekday - first_weekday) % 7

        if self.week < 5:
            return self.month, first_match + (self.week - 1) * 7

        candidate = first_match + 28
        if candidate <= days_total:
            return self.month, candidate
        return self.month, candidate - 7

    def _resolve_julian_rule(self, year: int) -> tuple[int, int]:
        day_of_year = self.day

        if is_leap_year(year) and day_of_year >= 60:
            day_of_year += 1

        return day_of_year_to_month_day(year, day_of_year)

    def _resolve_day_of_year_rule(self, year: int) -> tuple[int, int]:
        return day_of_year_to_month_day(year, self.day + 1)

    def _resolve_month_day(self, year: int) -> tuple[int, int]:
        if self.rule_type == "M":
            return self._resolve_month_week_day_rule(year)

        if self.rule_type == "J":
            return self._resolve_julian_rule(year)

        if self.rule_type == "N":
            return self._resolve_day_of_year_rule(year)

        raise ValueError(f"Unsupported rule type: {self.rule_type}")

    def get_transition(self, year: int) -> int:
        month, day = self._resolve_month_day(year)

        day_shift = self.seconds // 86400
        second_of_day = self.seconds % 86400

        hour = second_of_day // 3600
        minute = (second_of_day % 3600) // 60
        second = second_of_day % 60

        trans_year, trans_month, trans_day = shift_date(year, month, day, day_shift)

        naive_epoch = datetime_to_epoch(
            trans_year, trans_month, trans_day, hour, minute, second
        )
        return int(naive_epoch) - self.transition_offset_seconds

    def __repr__(self) -> str:
        return (
            f"_TransitionRule(posix_rule={self.posix_rule}, "
            f"rule_type={self.rule_type}, "
            f"month={self.month}, week={self.week}, weekday={self.weekday}, "
            f"day={self.day}, seconds={self.seconds})"
        )
