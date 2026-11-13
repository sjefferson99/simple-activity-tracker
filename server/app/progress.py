"""Period totals, trends and records for the Progress page (issue #190).

Everything here works on one user's analysed activities of one type, loaded
as small ActivityStat rows (a few hundred per user, so summing in Python is
cheap). Period boundaries are in the viewer's own timezone, passed from the
browser, since the server has no per-user zone (D2): weeks start Monday, and
"this week so far" is compared with the same span of last week.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.activity_analysis import ActivityAnalysis, AnalysisStatus

_TZ_NAME_MAX_LENGTH = 64

# D5: a "fastest ride" record only counts activities at least this long, so
# a short test ride can't hold it. Cycling uses 5 km, not the 10 km first
# planned: the dev data's typical ride is an ~8.5 km commute, which a 10 km
# floor would have excluded.
_FASTEST_MIN_DISTANCE_M_BY_TYPE = {"cycling": 5000.0, "running": 3000.0, "walking": 3000.0}
_DEFAULT_FASTEST_MIN_DISTANCE_M = 3000.0

# Activities shorter than this are left out of the speed trend: GPS noise
# dominates a few hundred metres' average speed.
_TREND_MIN_DISTANCE_M = 1000.0
TREND_ROLLING_WINDOW = 10

_WEEKS_SHOWN = 26
_MONTHS_SHOWN = 24


def resolve_timezone(name: str | None) -> tuple[tzinfo, str]:
    """The browser's IANA zone name, or UTC when it's missing or unknown.
    Returns the zone and the name actually used."""
    if name and len(name) <= _TZ_NAME_MAX_LENGTH:
        try:
            return ZoneInfo(name), name
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return UTC, "UTC"


@dataclass(frozen=True)
class ActivityStat:
    id: str
    title: str | None
    started_at: datetime
    distance_m: float
    moving_s: float
    elapsed_s: float | None
    gain_m: float | None
    # Counted in totals, but never in trends or records (issue #190).
    is_virtual: bool = False

    @property
    def avg_speed_mps(self) -> float | None:
        return self.distance_m / self.moving_s if self.moving_s > 0 else None


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def activity_types_for(session: Session, user_id: str) -> list[str]:
    """The types this user has analysed activities of, most-used first."""
    count = func.count(Activity.id)
    rows = session.execute(
        select(Activity.activity_type, count)
        .join(ActivityAnalysis, ActivityAnalysis.activity_id == Activity.id)
        .where(Activity.user_id == user_id, ActivityAnalysis.status == AnalysisStatus.done)
        .group_by(Activity.activity_type)
        .order_by(count.desc(), Activity.activity_type)
    )
    return [activity_type for activity_type, _ in rows]


def load_activity_stats(session: Session, user_id: str, activity_type: str) -> list[ActivityStat]:
    """The user's own analysed activities of this type (D1: never shared
    ones), oldest first."""
    rows = session.execute(
        select(
            Activity.id,
            Activity.title,
            Activity.started_at,
            ActivityAnalysis.distance_meters,
            ActivityAnalysis.moving_seconds,
            ActivityAnalysis.elapsed_seconds,
            ActivityAnalysis.elevation_gain_m,
            Activity.is_virtual,
        )
        .join(ActivityAnalysis, ActivityAnalysis.activity_id == Activity.id)
        .where(
            Activity.user_id == user_id,
            Activity.activity_type == activity_type,
            ActivityAnalysis.status == AnalysisStatus.done,
        )
        .order_by(Activity.started_at)
    )
    return [
        ActivityStat(
            id=row[0],
            title=row[1],
            started_at=_as_utc(row[2]),
            distance_m=row[3],
            moving_s=row[4],
            elapsed_s=row[5],
            gain_m=row[6],
            is_virtual=row[7],
        )
        for row in rows
    ]


@dataclass(frozen=True)
class Totals:
    count: int = 0
    distance_m: float = 0.0
    moving_s: float = 0.0
    gain_m: float = 0.0

    @property
    def avg_speed_mps(self) -> float | None:
        return self.distance_m / self.moving_s if self.moving_s > 0 else None


def totals(stats: Sequence[ActivityStat]) -> Totals:
    return Totals(
        count=len(stats),
        distance_m=sum(s.distance_m for s in stats),
        moving_s=sum(s.moving_s for s in stats),
        gain_m=sum(s.gain_m or 0.0 for s in stats),
    )


def _between(stats: Sequence[ActivityStat], start: datetime, end: datetime) -> list[ActivityStat]:
    """Activities started in [start, end); bounds are aware datetimes."""
    return [s for s in stats if start <= s.started_at < end]


class Granularity(StrEnum):
    week = "week"
    month = "month"
    year = "year"


def _period_start(local: datetime, granularity: Granularity) -> datetime:
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if granularity is Granularity.week:
        return midnight - timedelta(days=midnight.weekday())
    if granularity is Granularity.month:
        return midnight.replace(day=1)
    return midnight.replace(month=1, day=1)


def _previous_start(start: datetime, granularity: Granularity) -> datetime:
    if granularity is Granularity.week:
        return start - timedelta(days=7)
    if granularity is Granularity.month:
        return (start - timedelta(days=1)).replace(day=1)
    return start.replace(year=start.year - 1)


def _next_start(start: datetime, granularity: Granularity) -> datetime:
    if granularity is Granularity.week:
        return start + timedelta(days=7)
    if granularity is Granularity.month:
        return (start + timedelta(days=32)).replace(day=1)
    return start.replace(year=start.year + 1)


def _localize(naive: datetime, tz: tzinfo) -> datetime:
    """A wall-clock time in `tz`, as an aware datetime. Arithmetic on these
    stays wall-clock (Python doesn't re-resolve the offset), so week/month
    boundaries are local midnights across a DST change; re-attaching the
    zone here picks the right offset for each boundary."""
    return naive.replace(tzinfo=tz)


@dataclass(frozen=True)
class PeriodComparison:
    granularity: Granularity
    current: Totals
    previous: Totals


def compare_periods(
    stats: Sequence[ActivityStat], tz: tzinfo, now: datetime
) -> list[PeriodComparison]:
    """This week, month and year so far, each against the same span of the
    previous one (D2): on a Wednesday at 10:00, Monday 00:00 → now against
    last Monday 00:00 → last Wednesday 10:00. The previous span is clamped
    to its own period, so 31 March compares with all of February."""
    local_now = now.astimezone(tz).replace(tzinfo=None)
    comparisons = []
    for granularity in Granularity:
        start = _period_start(local_now, granularity)
        previous_start = _previous_start(start, granularity)
        previous_end = min(previous_start + (local_now - start), start)
        comparisons.append(
            PeriodComparison(
                granularity=granularity,
                current=totals(_between(stats, _localize(start, tz), now)),
                previous=totals(
                    _between(stats, _localize(previous_start, tz), _localize(previous_end, tz))
                ),
            )
        )
    return comparisons


@dataclass(frozen=True)
class PeriodBucket:
    start: date
    label: str
    totals: Totals


def _bucket_label(start: datetime, granularity: Granularity) -> str:
    if granularity is Granularity.week:
        return start.strftime("%d %b %Y")
    if granularity is Granularity.month:
        return start.strftime("%b %Y")
    return str(start.year)


def period_buckets(
    stats: Sequence[ActivityStat], tz: tzinfo, granularity: Granularity, now: datetime
) -> list[PeriodBucket]:
    """Totals per week (last 26), month (last 24) or year (every year since
    the first activity), oldest first, including empty periods so the chart
    has no gaps."""
    local_now = now.astimezone(tz).replace(tzinfo=None)
    last_start = _period_start(local_now, granularity)
    if granularity is Granularity.year:
        first_year = (
            min(s.started_at for s in stats).astimezone(tz).year if stats else local_now.year
        )
        starts = [last_start.replace(year=y) for y in range(first_year, local_now.year + 1)]
    else:
        shown = _WEEKS_SHOWN if granularity is Granularity.week else _MONTHS_SHOWN
        starts = [last_start]
        for _ in range(shown - 1):
            starts.append(_previous_start(starts[-1], granularity))
        starts.reverse()

    buckets = []
    for start in starts:
        end = _next_start(start, granularity)
        in_bucket = _between(stats, _localize(start, tz), _localize(end, tz))
        buckets.append(
            PeriodBucket(
                start=start.date(),
                label=_bucket_label(start, granularity),
                totals=totals(in_bucket),
            )
        )
    return buckets


@dataclass(frozen=True)
class TrendPoint:
    activity_id: str
    started_at: datetime
    distance_m: float
    avg_speed_mps: float
    rolling_distance_m: float
    rolling_speed_mps: float


def _rolling_mean(values: Sequence[float], window: int) -> list[float]:
    out = []
    for i in range(len(values)):
        chunk = values[max(0, i - window + 1) : i + 1]
        out.append(sum(chunk) / len(chunk))
    return out


def trend(stats: Sequence[ActivityStat], window: int = TREND_ROLLING_WINDOW) -> list[TrendPoint]:
    """Distance and average moving speed per activity, oldest first, each
    with the mean of the last `window` activities (fewer at the start)."""
    usable = [
        s
        for s in stats
        if not s.is_virtual
        and s.distance_m >= _TREND_MIN_DISTANCE_M
        and s.avg_speed_mps is not None
    ]
    distances = [s.distance_m for s in usable]
    speeds = [s.avg_speed_mps or 0.0 for s in usable]
    rolling_distances = _rolling_mean(distances, window)
    rolling_speeds = _rolling_mean(speeds, window)
    return [
        TrendPoint(
            activity_id=s.id,
            started_at=s.started_at,
            distance_m=s.distance_m,
            avg_speed_mps=speeds[i],
            rolling_distance_m=rolling_distances[i],
            rolling_speed_mps=rolling_speeds[i],
        )
        for i, s in enumerate(usable)
    ]


@dataclass(frozen=True)
class ActivityRecord:
    key: str
    label: str
    activity: ActivityStat
    value: float


_Metric = Callable[[ActivityStat], float | None]


def _best(stats: Sequence[ActivityStat], value: _Metric) -> tuple[ActivityStat, float] | None:
    """Highest value; on a tie the earlier activity keeps the record."""
    best: tuple[ActivityStat, float] | None = None
    for s in stats:
        v = value(s)
        if v is not None and (best is None or v > best[1]):
            best = (s, v)
    return best


def activity_records(stats: Sequence[ActivityStat], activity_type: str) -> list[ActivityRecord]:
    """Longest distance, longest moving time, biggest climb and fastest
    average moving speed (D5, with a minimum distance). Outdoor activities
    only: a virtual ride never holds a record."""
    stats = [s for s in stats if not s.is_virtual]
    min_fastest = _FASTEST_MIN_DISTANCE_M_BY_TYPE.get(
        activity_type, _DEFAULT_FASTEST_MIN_DISTANCE_M
    )
    candidates: list[
        tuple[str, str, Sequence[ActivityStat], Callable[[ActivityStat], float | None]]
    ]
    candidates = [
        ("distance", "Longest distance", stats, lambda s: s.distance_m),
        ("moving_time", "Longest moving time", stats, lambda s: s.moving_s),
        ("climb", "Biggest climb", stats, lambda s: s.gain_m),
        (
            "fastest",
            f"Fastest average speed ({min_fastest / 1000:g} km+)",
            [s for s in stats if s.distance_m >= min_fastest],
            lambda s: s.avg_speed_mps,
        ),
    ]
    records = []
    for key, label, pool, value in candidates:
        best = _best(pool, value)
        if best is not None:
            records.append(ActivityRecord(key=key, label=label, activity=best[0], value=best[1]))
    return records
