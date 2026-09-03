from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.analysis.gpx_parser import parse_gpx
from app.analysis.track import Point, Segment, Track
from app.analysis.v1 import AnalyzerV1

_FIXTURE = Path(__file__).parent / "fixtures" / "sample_run.gpx"

# Fixture parameters (see tests/fixtures/generate_sample_run.py):
# 3km at a constant 5:00 min/km pace, split into two segments with a 90s
# gap, +20m elevation climb spread evenly over the distance.
_EXPECTED_DISTANCE_M = 3000.0
_EXPECTED_MOVING_S = 900.0  # 3km at 5:00/km
_EXPECTED_ELAPSED_S = 900.0 + 90.0  # moving time + the inserted gap
_EXPECTED_AVG_SPEED_MPS = _EXPECTED_DISTANCE_M / _EXPECTED_MOVING_S


def _analyze() -> dict:
    track = parse_gpx(_FIXTURE.read_bytes())
    return AnalyzerV1().analyze(track)


def test_distance_matches_expected() -> None:
    result = _analyze()
    assert result["distance_meters"] == pytest.approx(_EXPECTED_DISTANCE_M, rel=0.01)


def test_moving_time_matches_expected() -> None:
    result = _analyze()
    assert result["moving_seconds"] == pytest.approx(_EXPECTED_MOVING_S, abs=2.0)


def test_elapsed_time_includes_the_segment_gap() -> None:
    result = _analyze()
    assert result["elapsed_seconds"] == pytest.approx(_EXPECTED_ELAPSED_S, abs=1.0)


def test_average_moving_speed_matches_expected_pace() -> None:
    result = _analyze()
    assert result["avg_moving_speed_mps"] == pytest.approx(_EXPECTED_AVG_SPEED_MPS, rel=0.02)


def test_splits_cover_three_kilometres_at_the_expected_pace() -> None:
    result = _analyze()
    splits = result["splits"]
    assert len(splits) == 3
    for split in splits:
        assert split["duration_seconds"] == pytest.approx(300.0, abs=5.0)
        assert split["avg_speed_mps"] == pytest.approx(_EXPECTED_AVG_SPEED_MPS, rel=0.05)


def test_elevation_gain_matches_the_climb_with_no_loss() -> None:
    result = _analyze()
    elevation = result["elevation"]
    assert elevation["gain_m"] == pytest.approx(20.0, abs=1.0)
    assert elevation["loss_m"] == pytest.approx(0.0, abs=1.0)


def test_best_efforts_cover_1k_and_are_close_to_expected_pace() -> None:
    result = _analyze()
    efforts = {e["distance_meters"]: e for e in result["best_efforts"]}
    assert 1000.0 in efforts
    assert efforts[1000.0]["duration_seconds"] == pytest.approx(300.0, abs=5.0)
    # only 3km total, so 5k/10k windows should not appear
    assert 5000.0 not in efforts
    assert 10000.0 not in efforts


def test_series_is_bounded_and_spans_the_whole_run() -> None:
    result = _analyze()
    series = result["series"]
    assert 0 < len(series) <= 301
    assert series[0]["t_s"] == 0.0
    # t_s tracks accumulated moving time (like splits/moving_seconds), not
    # wall-clock elapsed — the 90s segment gap contributes no t_s, the same
    # way it contributes no moving_seconds.
    assert series[-1]["t_s"] == pytest.approx(_EXPECTED_MOVING_S, abs=1.0)


def _zigzag_track(
    *, n_points: int = 60, forward_step_m: float = 2.0, jitter_m: float = 3.0
) -> Track:
    """A track moving steadily east at one degree of longitude per
    111195m (matches the mobile MetricsEngine test fixture's convention),
    with every other point offset south then back — real GPS jitter at a
    ~1s sample rate is comparable in size to the actual distance covered
    per step, exactly what this shape reproduces. The average speed over
    any few-second window should still read close to forward_step_m/1s,
    even though consecutive single steps swing wildly positive and
    negative as the path zig-zags."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    points = []
    lon_per_meter = 1 / 111195
    for i in range(n_points):
        lon = i * forward_step_m * lon_per_meter
        lat = (jitter_m * lon_per_meter) if i % 2 else 0.0
        points.append(Point(lat=lat, lon=lon, ele=100.0, time=start + timedelta(seconds=i)))
    return Track(segments=[Segment(points=points)])


def test_series_speed_is_smoothed_over_a_time_window_not_per_step() -> None:
    """Regression for a real finding: the series' speed_mps used to be each
    step's raw instant speed (distance over ~1s between two consecutive
    fixes), which is dominated by GPS jitter at that timescale and made the
    pace chart's line far noisier than the underlying pace actually was —
    visibly worse than the elevation line, which already got smoothing.
    Windowing it the same way mobile MetricsEngine smooths current speed
    (displacement over the last few seconds, not a single step) should keep
    the series close to the true average pace despite per-step jitter, once
    the window has enough history to span a full jitter cycle — only the
    very first sample or two (window too short) can still show the swing.

    On this fixture, every single *raw* per-step speed reads ~3.6 m/s (the
    zig-zag's Pythagorean hop distance), never the true ~2 m/s forward
    pace — so a tight per-sample bound here only holds if speeds are
    actually windowed, not per-step."""
    track = _zigzag_track(forward_step_m=2.0, jitter_m=3.0)
    result = AnalyzerV1().analyze(track)

    speeds = [s["speed_mps"] for s in result["series"] if s["speed_mps"] is not None]
    assert len(speeds) > 5, "expected several non-null speeds in the series"
    # Skip the startup transient (the window can't smooth before it has
    # enough history) and check the rest sits tightly on the true pace.
    for speed in speeds[2:]:
        assert speed == pytest.approx(2.0, abs=0.3)


def test_bounds_and_counts_are_populated() -> None:
    result = _analyze()
    assert result["bounds"] is not None
    assert result["point_count"] > 0
    assert result["segment_count"] == 2


def test_distance_is_never_negative() -> None:
    result = _analyze()
    assert result["distance_meters"] >= 0


def test_split_distances_sum_to_approximately_total_distance() -> None:
    result = _analyze()
    # 3 completed 1km splits should cover ~all of a 3km run.
    assert len(result["splits"]) * 1000.0 == pytest.approx(result["distance_meters"], rel=0.02)


def test_elevation_gain_is_never_negative() -> None:
    result = _analyze()
    assert result["elevation"]["gain_m"] >= 0
    assert result["elevation"]["loss_m"] >= 0
