"""Progress page logic (issue #190): timezone-aware period comparisons and
buckets, trends, and activity records. Pure functions over ActivityStat rows,
so no database here; see test_progress_web.py for the page and the records
that come from the database."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.analysis.v1 import best_effort_distances
from app.progress import (
    ActivityStat,
    Granularity,
    activity_records,
    compare_periods,
    period_buckets,
    resolve_timezone,
    trend,
)
from app.web.formatting import format_effort_distance, format_rank

LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")


def _stat(
    started_at: datetime,
    *,
    distance_m: float = 5000.0,
    moving_s: float = 1500.0,
    gain_m: float | None = 10.0,
    activity_id: str | None = None,
) -> ActivityStat:
    return ActivityStat(
        id=activity_id or started_at.isoformat(),
        title=None,
        started_at=started_at.astimezone(UTC),
        distance_m=distance_m,
        moving_s=moving_s,
        elapsed_s=moving_s,
        gain_m=gain_m,
    )


def _comparison(stats, tz, now, granularity: Granularity):
    return next(c for c in compare_periods(stats, tz, now) if c.granularity is granularity)


# --- resolve_timezone ---------------------------------------------------------


def test_resolve_timezone_accepts_an_iana_name() -> None:
    tz, name = resolve_timezone("Europe/London")
    assert name == "Europe/London"
    assert tz == LONDON


@pytest.mark.parametrize("bad", [None, "", "Not/AZone", "../../etc/passwd", "A" * 65])
def test_resolve_timezone_falls_back_to_utc(bad) -> None:
    tz, name = resolve_timezone(bad)
    assert (tz, name) == (UTC, "UTC")


# --- compare_periods ----------------------------------------------------------


def test_week_so_far_compares_with_the_same_span_of_last_week() -> None:
    # Wednesday 2026-11-11 10:00 London. This week started Monday 9 Nov.
    now = datetime(2026, 11, 11, 10, 0, tzinfo=LONDON)
    stats = [
        _stat(datetime(2026, 11, 9, 8, 0, tzinfo=LONDON)),  # this week
        _stat(datetime(2026, 11, 3, 18, 0, tzinfo=LONDON)),  # last Tue: inside last week's span
        _stat(datetime(2026, 11, 4, 11, 0, tzinfo=LONDON)),  # last Wed 11:00: after the span
        _stat(datetime(2026, 11, 1, 23, 0, tzinfo=LONDON)),  # Sunday before: previous week
    ]
    week = _comparison(stats, LONDON, now.astimezone(UTC), Granularity.week)
    assert week.current.count == 1
    assert week.previous.count == 1
    assert week.current.distance_m == 5000.0


def test_month_comparison_is_clamped_to_the_previous_month() -> None:
    # 31 March: "last month at this point" can't run past 28 February.
    now = datetime(2026, 3, 31, 12, 0, tzinfo=LONDON)
    stats = [
        _stat(datetime(2026, 2, 28, 20, 0, tzinfo=LONDON)),
        _stat(datetime(2026, 3, 1, 0, 30, tzinfo=LONDON)),
    ]
    month = _comparison(stats, LONDON, now.astimezone(UTC), Granularity.month)
    assert month.previous.count == 1
    assert month.current.count == 1


def test_year_boundary_uses_the_viewers_timezone() -> None:
    # 03:00 UTC on 1 Jan is still 31 Dec in New York.
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    stats = [_stat(datetime(2026, 1, 1, 3, 0, tzinfo=UTC))]
    in_new_york = _comparison(stats, NEW_YORK, now, Granularity.year)
    in_utc = _comparison(stats, UTC, now, Granularity.year)
    assert in_new_york.current.count == 0
    assert in_utc.current.count == 1


def test_totals_sum_distance_time_and_climb_ignoring_missing_gain() -> None:
    now = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)
    stats = [
        _stat(datetime(2026, 11, 9, 8, 0, tzinfo=UTC), distance_m=8000, moving_s=1200, gain_m=40),
        _stat(datetime(2026, 11, 10, 8, 0, tzinfo=UTC), distance_m=2000, moving_s=600, gain_m=None),
    ]
    week = _comparison(stats, UTC, now, Granularity.week)
    assert week.current.count == 2
    assert week.current.distance_m == 10000
    assert week.current.moving_s == 1800
    assert week.current.gain_m == 40


# --- period_buckets -----------------------------------------------------------


def test_week_buckets_start_on_monday_across_a_dst_change() -> None:
    # UK clocks went forward on Sunday 29 March 2026. 00:30 on Monday 30
    # March London is 23:30 UTC on the Sunday: it belongs to the new week.
    now = datetime(2026, 4, 2, 12, 0, tzinfo=UTC)
    stats = [_stat(datetime(2026, 3, 30, 0, 30, tzinfo=LONDON))]
    buckets = period_buckets(stats, LONDON, Granularity.week, now)
    assert len(buckets) == 26
    assert buckets[-1].start.isoformat() == "2026-03-30"
    assert buckets[-1].totals.count == 1
    assert buckets[-2].totals.count == 0
    assert all(b.start.weekday() == 0 for b in buckets)


def test_month_buckets_include_empty_months_oldest_first() -> None:
    now = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
    stats = [_stat(datetime(2026, 9, 5, 8, 0, tzinfo=UTC))]
    buckets = period_buckets(stats, UTC, Granularity.month, now)
    assert len(buckets) == 24
    assert buckets[-1].label == "Nov 2026"
    assert buckets[0].label == "Dec 2024"
    counts = {b.label: b.totals.count for b in buckets}
    assert counts["Sep 2026"] == 1
    assert counts["Oct 2026"] == 0


def test_year_buckets_run_from_the_first_activity_to_now() -> None:
    now = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
    stats = [
        _stat(datetime(2024, 9, 18, 8, 0, tzinfo=UTC)),
        _stat(datetime(2026, 1, 2, 8, 0, tzinfo=UTC)),
    ]
    buckets = period_buckets(stats, UTC, Granularity.year, now)
    assert [(b.label, b.totals.count) for b in buckets] == [("2024", 1), ("2025", 0), ("2026", 1)]


def test_year_buckets_with_no_activities_show_just_this_year() -> None:
    now = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
    assert [b.label for b in period_buckets([], UTC, Granularity.year, now)] == ["2026"]


# --- trend --------------------------------------------------------------------


def test_trend_rolls_the_mean_of_the_last_n_and_skips_short_activities() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    stats = [
        _stat(start, distance_m=2000, moving_s=1000),  # 2.0 m/s
        _stat(start + timedelta(days=1), distance_m=500, moving_s=100),  # too short
        _stat(start + timedelta(days=2), distance_m=4000, moving_s=1000),  # 4.0 m/s
        _stat(start + timedelta(days=3), distance_m=6000, moving_s=1000),  # 6.0 m/s
    ]
    points = trend(stats, window=2)
    assert [p.avg_speed_mps for p in points] == [2.0, 4.0, 6.0]
    assert [p.rolling_speed_mps for p in points] == [2.0, 3.0, 5.0]
    assert [p.rolling_distance_m for p in points] == [2000, 3000, 5000]


def test_trend_skips_activities_with_no_moving_time() -> None:
    stats = [_stat(datetime(2026, 1, 1, tzinfo=UTC), moving_s=0)]
    assert trend(stats) == []


# --- activity_records ---------------------------------------------------------


def test_fastest_record_ignores_rides_under_the_minimum_distance() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    stats = [
        _stat(start, distance_m=1000, moving_s=50, activity_id="sprint"),  # 20 m/s, too short
        _stat(start + timedelta(days=1), distance_m=8500, moving_s=1500, activity_id="commute"),
    ]
    records = {r.key: r for r in activity_records(stats, "cycling")}
    assert records["fastest"].activity.id == "commute"
    assert "5 km+" in records["fastest"].label


def test_records_tie_goes_to_the_earlier_activity() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    stats = [
        _stat(start, distance_m=8000, activity_id="first"),
        _stat(start + timedelta(days=1), distance_m=8000, activity_id="second"),
    ]
    records = {r.key: r for r in activity_records(stats, "running")}
    assert records["distance"].activity.id == "first"


def test_climb_record_is_absent_when_no_activity_has_altitude() -> None:
    stats = [_stat(datetime(2026, 1, 1, tzinfo=UTC), gain_m=None)]
    keys = {r.key for r in activity_records(stats, "running")}
    assert "climb" not in keys
    assert {"distance", "moving_time", "fastest"} <= keys


# --- best-effort distances and formatting ---------------------------------------


@pytest.mark.parametrize("activity_type", ["running", "walking", "cycling", "rowing"])
def test_every_type_keeps_the_1k_and_5k_released_apps_read(activity_type) -> None:
    distances = best_effort_distances(activity_type)
    assert 1000.0 in distances
    assert 5000.0 in distances


def test_cycling_and_running_have_their_own_distances() -> None:
    assert 100000.0 in best_effort_distances("cycling")
    assert 400.0 not in best_effort_distances("cycling")
    assert 42195.0 in best_effort_distances("running")


@pytest.mark.parametrize(
    ("meters", "label"),
    [
        (400.0, "400 m"),
        (1000.0, "1 km"),
        (1609.344, "1 mile"),
        (21097.5, "Half marathon"),
        (42195.0, "Marathon"),
        (100000.0, "100 km"),
        (None, "—"),
    ],
)
def test_format_effort_distance(meters, label) -> None:
    assert format_effort_distance(meters) == label


def test_format_rank() -> None:
    assert [format_rank(r) for r in (1, 2, 3, 4, None)] == ["PR", "2nd best", "3rd best", "", ""]


# --- virtual activities -------------------------------------------------------


def _virtual(stat: ActivityStat) -> ActivityStat:
    from dataclasses import replace

    return replace(stat, is_virtual=True)


def test_virtual_activities_count_in_totals_but_not_trends_or_records() -> None:
    now = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)
    outdoor = _stat(datetime(2026, 11, 9, 8, 0, tzinfo=UTC), distance_m=8000, activity_id="road")
    zwift = _virtual(
        _stat(datetime(2026, 11, 10, 8, 0, tzinfo=UTC), distance_m=30000, activity_id="zwift")
    )
    stats = [outdoor, zwift]

    week = _comparison(stats, UTC, now, Granularity.week)
    assert week.current.count == 2
    assert [p.activity_id for p in trend(stats)] == ["road"]
    assert {r.activity.id for r in activity_records(stats, "cycling")} == {"road"}
