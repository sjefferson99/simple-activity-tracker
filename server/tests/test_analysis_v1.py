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


def test_default_split_type_and_value_are_reported() -> None:
    result = _analyze()
    assert result["split_type"] == "distance_km"
    assert result["split_value"] == 1
    for split in result["splits"]:
        assert split["distance_m"] == pytest.approx(1000.0, rel=0.001)


def test_distance_mi_splits_use_the_mile_boundary() -> None:
    track = parse_gpx(_FIXTURE.read_bytes())
    result = AnalyzerV1().analyze(track, "distance_mi", 1)
    assert result["split_type"] == "distance_mi"
    assert result["split_value"] == 1
    splits = result["splits"]
    # 3km / 1609.344m per mile == 1 full mile split (a second mile never
    # completes within the 3km fixture).
    assert len(splits) == 1
    assert splits[0]["distance_m"] == pytest.approx(1609.344, rel=0.001)
    # 1 mile at 5:00/km pace: 1609.344m / (1000m / 300s) == 482.8s.
    assert splits[0]["duration_seconds"] == pytest.approx(482.8, abs=5.0)


def test_time_min_splits_interpolate_distance_at_the_time_boundary() -> None:
    track = parse_gpx(_FIXTURE.read_bytes())
    result = AnalyzerV1().analyze(track, "time_min", 2)
    assert result["split_type"] == "time_min"
    assert result["split_value"] == 2
    splits = result["splits"]
    # 900s of moving time / 120s per split == 7 completed 2-minute splits.
    assert len(splits) == 7
    for split in splits:
        assert split["duration_seconds"] == pytest.approx(120.0, abs=1.0)
        # 5:00/km pace covers 400m in 2 minutes.
        assert split["distance_m"] == pytest.approx(400.0, rel=0.05)


def test_split_boundary_carries_a_chart_time_and_position() -> None:
    result = _analyze()
    splits = result["splits"]
    # t_s should be the cumulative sum of duration_seconds up to and
    # including each split — i.e. it lines up with the series' own t_s axis,
    # which is what lets the chart draw a boundary line at the right x.
    cumulative_duration = 0.0
    for split in splits:
        cumulative_duration += split["duration_seconds"]
        boundary = split["boundary"]
        assert boundary["t_s"] == pytest.approx(cumulative_duration, abs=0.01)
        assert -90.0 <= boundary["lat"] <= 90.0
        assert -180.0 <= boundary["lon"] <= 180.0


def test_split_boundary_position_is_interpolated_along_a_sparse_step() -> None:
    # Straight line from (0, 0) to (0, 2500m-worth-of-lon) — each boundary's
    # lon should land proportionally to the distance covered (1000m/2500m,
    # 2000m/2500m).
    track = _sparse_track(total_distance_m=2500.0, total_duration_s=250.0)
    result = AnalyzerV1().analyze(track, "distance_km", 1)
    splits = result["splits"]
    lon_per_meter = 1 / 111195
    assert splits[0]["boundary"]["lat"] == pytest.approx(0.0, abs=1e-9)
    assert splits[0]["boundary"]["lon"] == pytest.approx(1000.0 * lon_per_meter, rel=0.001)
    assert splits[1]["boundary"]["lon"] == pytest.approx(2000.0 * lon_per_meter, rel=0.001)


def test_split_boundary_takes_the_short_way_across_the_antimeridian() -> None:
    """Regression: interpolating raw longitudes sent the marker the long way
    round at ±180°, landing it ~30km from the real crossing. Distances were
    never affected (haversine is wrap-safe), only the boundary position."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    # ~1km either side of the antimeridian, so the 1km boundary falls almost
    # exactly on it.
    points = [
        Point(lat=0.0, lon=179.9910, ele=None, time=start),
        Point(lat=0.0, lon=-179.9910, ele=None, time=start + timedelta(seconds=200)),
    ]
    result = AnalyzerV1().analyze(Track(segments=[Segment(points=points)]), "distance_km", 1)

    boundary = result["splits"][0]["boundary"]
    assert abs(boundary["lon"]) == pytest.approx(180.0, abs=0.01)
    assert -180.0 <= boundary["lon"] <= 180.0


def test_time_min_split_distances_sum_to_the_completed_split_time() -> None:
    track = parse_gpx(_FIXTURE.read_bytes())
    result = AnalyzerV1().analyze(track, "time_min", 2)
    splits = result["splits"]
    total_split_distance = sum(s["distance_m"] for s in splits)
    total_split_duration = sum(s["duration_seconds"] for s in splits)
    # Only whole 2-minute splits are counted (any trailing partial minute is
    # excluded, same as distance-mode's own incomplete trailing split) — at
    # the fixture's constant 5:00/km pace, distance and duration should still
    # agree with each other regardless of how many splits completed.
    assert total_split_distance == pytest.approx(
        total_split_duration * (_EXPECTED_DISTANCE_M / _EXPECTED_MOVING_S), rel=0.05
    )


def _sparse_track(total_distance_m: float, total_duration_s: float) -> Track:
    """A track with a single huge step (two points, one gap) — e.g. a
    backgrounded app resuming after several minutes, or a tunnel. Constant
    implied speed = total_distance_m / total_duration_s throughout."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    lon_per_meter = 1 / 111195
    points = [
        Point(lat=0, lon=0, ele=None, time=start),
        Point(
            lat=0,
            lon=total_distance_m * lon_per_meter,
            ele=None,
            time=start + timedelta(seconds=total_duration_s),
        ),
    ]
    return Track(segments=[Segment(points=points)])


def test_a_single_sparse_step_crossing_multiple_distance_boundaries_produces_every_split() -> None:
    """Regression: _compute_distance_splits used to check the boundary with
    `if` instead of `while`, so a single step spanning several split
    boundaries (a sparse/gapped GPX — exactly what mobile's own plausibility
    gate is designed to tolerate) only produced the first split crossed,
    silently dropping the rest."""
    # 2500m over 250s at 10 m/s crosses the 1km boundary twice (1000m, 2000m).
    track = _sparse_track(total_distance_m=2500.0, total_duration_s=250.0)
    result = AnalyzerV1().analyze(track, "distance_km", 1)
    splits = result["splits"]
    assert len(splits) == 2
    assert splits[0]["index"] == 1
    assert splits[1]["index"] == 2
    for split in splits:
        assert split["distance_m"] == pytest.approx(1000.0, rel=0.001)
        assert split["duration_seconds"] == pytest.approx(100.0, abs=0.5)


def test_a_single_sparse_step_crossing_multiple_time_boundaries_produces_every_split() -> None:
    """Time-mode mirror of the distance-mode regression above."""
    # 600m over 300s (2 m/s) crosses the 2-minute (120s) boundary twice.
    track = _sparse_track(total_distance_m=600.0, total_duration_s=300.0)
    result = AnalyzerV1().analyze(track, "time_min", 2)
    splits = result["splits"]
    assert len(splits) == 2
    assert splits[0]["index"] == 1
    assert splits[1]["index"] == 2
    for split in splits:
        assert split["duration_seconds"] == pytest.approx(120.0, abs=0.5)
        assert split["distance_m"] == pytest.approx(240.0, rel=0.01)
