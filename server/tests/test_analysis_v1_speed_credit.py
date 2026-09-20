"""Issue #50: AnalyzerV1's moving-time gate now reads sat:speed via the
phone's tuned hysteresis (_StationaryDetector) instead of a single-step
threshold with no confirmation, and best-effort windows trim to the exact
target distance instead of reporting a raw overshot window's time. Credited
distance itself is still the position delta (haversine) — a Doppler
chip-speed-integration formula was tried and reverted after real wheel-
speed-sensor-verified rides showed it less accurate than position-summing.
elapsed_seconds now excludes the gap between GPX track segments (a pause
starts a new segment on the phone), closing most of the drift against the
phone's own pause-excluding "Time" tile. See the ANALYSIS_VERSION=10 note in
app/analysis/v1.py for the full rationale."""

from datetime import UTC, datetime, timedelta

import pytest

from app.analysis.track import Point, Segment, Track
from app.analysis.v1 import AnalyzerV1

_START = datetime(2026, 1, 1, tzinfo=UTC)
_LON_PER_METER = 1 / 111195


def _moving_points(
    *,
    n_points: int,
    step_m: float,
    step_s: float,
    speed_mps: float | None,
) -> list[Point]:
    """A straight line moving east, n_points fixes step_s apart, each
    step_m further along — every point carries the same chip speed_mps
    (None to omit sat:speed entirely, exercising the position-delta
    fallback the stationary gate uses when a fix has no usable speed)."""
    points = []
    for i in range(n_points):
        lon = i * step_m * _LON_PER_METER
        points.append(
            Point(
                lat=0.0,
                lon=lon,
                ele=100.0,
                time=_START + timedelta(seconds=i * step_s),
                speed_mps=speed_mps,
            )
        )
    return points


def _track(points: list[Point]) -> Track:
    return Track(segments=[Segment(points=points)])


def test_credited_distance_is_always_the_position_delta() -> None:
    """A moving segment credits the position delta even when sat:speed is
    present and would (under a Doppler-integration formula) imply a
    different distance — sat:speed only drives the stationary gate, never
    the distance itself."""
    points = _moving_points(n_points=10, step_m=2.0, step_s=1.0, speed_mps=1.0)
    result = AnalyzerV1().analyze(_track(points))
    credited_steps = (len(points) - 1) - 3  # minus the enter-confirm lag
    assert result["distance_meters"] == pytest.approx(credited_steps * 2.0, rel=0.02)


def test_distance_with_no_speed_data_falls_back_to_the_noise_floor_gate() -> None:
    """A GPX with no sat:speed at all must still credit real motion — the
    stationary gate falls back to the position noise floor, and credited
    distance is the position delta either way, so results are unaffected by
    the absence of speed data (old GPX files, non-mobile imports)."""
    points = _moving_points(n_points=10, step_m=2.0, step_s=1.0, speed_mps=None)
    result = AnalyzerV1().analyze(_track(points))
    assert result["distance_meters"] == pytest.approx(9 * 2.0, rel=0.02)


def test_stationary_chip_speed_noise_credits_only_the_documented_residual() -> None:
    """Mirrors the exact real capture docs/GPS-METRICS-PLAN.md step 3a
    describes: a noise blip (4.32 m/s) that rings for two more decaying
    fixes (0.71, 0.62) before dropping off. The 3-fix confirmation streak
    completes on the third of these, so one step (~1s, ~0.4m at these
    speeds) is credited before the very next fix (0.1 m/s) drops back below
    the exit threshold — the same small residual the plan calls "mostly
    rejects, not entirely" for a 3-fix streak, as opposed to the ~5m a
    2-fix streak would have let through. This is documented, accepted
    behaviour, not a bug: the assertion pins the residual to stay small."""
    points = [
        Point(lat=0.0, lon=0.0, ele=100.0, time=_START, speed_mps=0.0),
        Point(
            lat=0.0,
            lon=0.5 * _LON_PER_METER,
            ele=100.0,
            time=_START + timedelta(seconds=1),
            speed_mps=4.32,  # one noisy fix, matches the real capture in the plan
        ),
        Point(
            lat=0.0,
            lon=1.0 * _LON_PER_METER,
            ele=100.0,
            time=_START + timedelta(seconds=2),
            speed_mps=0.71,
        ),
        Point(
            lat=0.0,
            lon=1.5 * _LON_PER_METER,
            ele=100.0,
            time=_START + timedelta(seconds=3),
            speed_mps=0.62,
        ),
        Point(
            lat=0.0,
            lon=2.0 * _LON_PER_METER,
            ele=100.0,
            time=_START + timedelta(seconds=4),
            speed_mps=0.1,
        ),
    ]
    result = AnalyzerV1().analyze(_track(points))
    assert result["distance_meters"] < 1.0
    assert result["moving_seconds"] <= 1.0


def test_moving_time_requires_three_consecutive_fixes_above_enter_threshold() -> None:
    """A real walk (steady chip speed above the 0.6 m/s enter threshold)
    should register as moving once the 3-fix confirmation streak completes,
    and keep crediting distance/time for the remainder — verifies the
    hysteresis gate actually opens, not just that it rejects noise."""
    points = _moving_points(n_points=10, step_m=1.0, step_s=1.0, speed_mps=1.0)
    result = AnalyzerV1().analyze(_track(points))
    # First 3 fixes build the confirmation streak (not yet moving); steps 4-9
    # onward are credited. Exact count depends on the "verdict is whatever
    # was true before this fix" rule (see _StationaryDetector.accepts).
    assert result["moving_seconds"] > 0
    assert result["distance_meters"] > 0
    assert result["moving_seconds"] < 9.0  # less than the full elapsed span


def test_exit_moving_needs_only_one_fix_below_exit_threshold() -> None:
    """Once moving, a single fix below the 0.4 m/s exit threshold should
    immediately stop crediting distance/time — no confirmation streak
    required to leave the moving state, unlike entering it."""
    fast = _moving_points(n_points=5, step_m=1.0, step_s=1.0, speed_mps=1.0)
    slow_start = fast[-1].time
    slow = [
        Point(
            lat=0.0,
            lon=(5 + i) * 1.0 * _LON_PER_METER,
            ele=100.0,
            time=slow_start + timedelta(seconds=i + 1),
            speed_mps=0.1,
        )
        for i in range(5)
    ]
    result = AnalyzerV1().analyze(_track(fast + slow))
    # Moving time should stop accumulating once the slow stretch begins —
    # well under the full ~9s elapsed span.
    assert result["moving_seconds"] < 6.0


def test_best_effort_window_trims_to_exact_target_distance() -> None:
    """Issue #50 cause 1: a 1200m track at a steady 2.5 m/s (so the window
    naturally overshoots the 1000m target between fixes) must report the
    1000m best effort's duration as exactly 1000/2.5=400s, not the raw time
    for the full overshot window."""
    points = _moving_points(n_points=25, step_m=50.0, step_s=20.0, speed_mps=2.5)
    result = AnalyzerV1().analyze(_track(points))
    efforts = {e["distance_meters"]: e for e in result["best_efforts"]}
    assert 1000.0 in efforts
    assert efforts[1000.0]["duration_seconds"] == pytest.approx(400.0, rel=0.01)
    assert efforts[1000.0]["avg_speed_mps"] == pytest.approx(2.5, rel=0.01)


def test_elapsed_seconds_excludes_the_gap_between_track_segments() -> None:
    """Mobile starts a new <trkseg> on every pause/resume (RunGpxLog) — the
    gap between two segments is paused wall-clock time, the same time the
    phone's own "Time" tile (RunClock) excludes. elapsed_seconds must
    exclude it too, summing each segment's own span instead of the whole
    track's first-to-last."""
    first_segment = _moving_points(n_points=5, step_m=1.0, step_s=1.0, speed_mps=1.0)
    pause_gap = timedelta(minutes=10)
    second_start = first_segment[-1].time + pause_gap
    second_segment = [
        Point(
            lat=0.0,
            lon=(5 + i) * 1.0 * _LON_PER_METER,
            ele=100.0,
            time=second_start + timedelta(seconds=i),
            speed_mps=1.0,
        )
        for i in range(5)
    ]
    track = Track(segments=[Segment(points=first_segment), Segment(points=second_segment)])
    result = AnalyzerV1().analyze(track)

    # Each segment spans 4s (5 points, 1s apart); the 10-minute gap between
    # them must not appear in elapsed_seconds at all.
    assert result["elapsed_seconds"] == pytest.approx(8.0, abs=0.01)
    assert result["elapsed_seconds"] < pause_gap.total_seconds()


def test_elapsed_seconds_matches_first_to_last_with_a_single_segment() -> None:
    """A track with no pauses (one segment) is unaffected by the
    per-segment-span calculation — it collapses to the same first-to-last
    span as before this change."""
    points = _moving_points(n_points=10, step_m=1.0, step_s=1.0, speed_mps=1.0)
    result = AnalyzerV1().analyze(_track(points))
    assert result["elapsed_seconds"] == pytest.approx(9.0, abs=0.01)
