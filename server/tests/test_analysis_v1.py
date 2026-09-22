from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.analysis.gpx_parser import SplitPlanData, parse_gpx
from app.analysis.track import Point, Segment, Track
from app.analysis.v1 import AnalyzerV1, _verdict

_FIXTURE = Path(__file__).parent / "fixtures" / "sample_run.gpx"

# Fixture parameters (see tests/fixtures/generate_sample_run.py):
# 3km at a constant 5:00 min/km pace, split into two segments with a 90s
# gap, +20m elevation climb spread evenly over the distance.
_EXPECTED_DISTANCE_M = 3000.0
_EXPECTED_MOVING_S = 900.0  # 3km at 5:00/km
# elapsed_seconds sums each segment's own span, excluding the gap between
# them — the same 90s a pause/resume on the phone would exclude from its
# own "Time" tile (issue #50). Equal to moving time here since this
# synthetic fixture has no within-segment stationary stretches.
_EXPECTED_ELAPSED_S = 900.0
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


def test_elapsed_time_excludes_the_segment_gap() -> None:
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


def test_start_and_end_match_the_track_endpoints() -> None:
    """Regression for issue #76: the analysis result must carry the run's
    start/finish coordinates so ActivityAnalysis.start_lat/start_lon/
    end_lat/end_lon (and later, location search) can be derived from it."""
    track = parse_gpx(_FIXTURE.read_bytes())
    result = AnalyzerV1().analyze(track)

    first_point = track.segments[0].points[0]
    last_point = track.segments[-1].points[-1]
    assert result["start"] == {"lat": first_point.lat, "lon": first_point.lon}
    assert result["end"] == {"lat": last_point.lat, "lon": last_point.lon}
    # The fixture's two segments (a pause/resume gap) don't share a start
    # point, so this also confirms start/end aren't accidentally both drawn
    # from the same (e.g. first) segment.
    assert result["start"] != result["end"]


def test_start_equals_end_for_a_single_point_track() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    track = Track(segments=[Segment(points=[Point(lat=51.5, lon=-0.1, ele=10.0, time=start)])])
    result = AnalyzerV1().analyze(track)
    assert result["start"] == {"lat": 51.5, "lon": -0.1}
    assert result["end"] == {"lat": 51.5, "lon": -0.1}


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
        # boundary.dist_m (issue #58) is the interpolated cumulative distance
        # at the time boundary, i.e. index * 400m at this pace.
        assert split["boundary"]["dist_m"] == pytest.approx(split["index"] * 400.0, rel=0.05)


def test_split_boundary_carries_a_chart_time_and_position() -> None:
    result = _analyze()
    splits = result["splits"]
    # t_s should be the cumulative sum of duration_seconds up to and
    # including each split — i.e. it lines up with the series' own t_s axis,
    # which is what lets the chart draw a boundary line at the right x.
    # dist_m is the mirror image for a distance-based x-axis (issue #58) —
    # here it's exact km boundaries, since these are distance-mode splits.
    cumulative_duration = 0.0
    for split in splits:
        cumulative_duration += split["duration_seconds"]
        boundary = split["boundary"]
        assert boundary["t_s"] == pytest.approx(cumulative_duration, abs=0.01)
        assert boundary["dist_m"] == pytest.approx(split["index"] * 1000.0, rel=0.001)
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


def test_custom_plan_produces_variable_sized_splits_with_targets() -> None:
    """Issue #100: a custom plan's splits (400m, 1000m, 200m here) must each
    be sized and targeted individually, mirroring mobile's own
    SplitPlan-generalized MetricsEngine test (docs/SPLIT-TARGETS-PLAN.md
    §6.1). A constant 4 m/s track lets duration fall straight out of size."""
    # A hair over 1600m so the final 200m split genuinely completes despite
    # haversine's tiny approximation error versus the nominal lon offset.
    track = _sparse_track(total_distance_m=1600.1, total_duration_s=400.025)  # 4 m/s throughout
    plan = SplitPlanData(
        split_type="distance_km",
        split_value=1,
        rolling_target_mps=None,
        custom_splits=[(400.0, 5.0), (1000.0, 3.0), (200.0, None)],
    )
    result = AnalyzerV1().analyze(track, "distance_km", 1, split_plan=plan)
    splits = result["splits"]
    assert len(splits) == 3
    assert [s["distance_m"] for s in splits] == pytest.approx([400.0, 1000.0, 200.0], rel=0.001)
    assert splits[0]["target_speed_mps"] == 5.0
    assert splits[0]["verdict"] == "too_slow"  # 4 m/s actual vs 5 m/s target
    assert splits[1]["target_speed_mps"] == 3.0
    assert splits[1]["verdict"] == "too_fast"  # 4 m/s actual vs 3 m/s target
    assert splits[2]["target_speed_mps"] is None
    assert splits[2]["verdict"] is None
    assert result["split_targets_as"] == "pace"


def test_custom_plan_rolls_on_at_base_size_with_no_target_once_exhausted() -> None:
    """Issue #99 D5: after a custom plan's splits are used up, further
    splits continue at the rolling split_type/split_value size with no
    target — no special-casing beyond _SplitSizing falling through to
    base_size/None."""
    track = _sparse_track(total_distance_m=2500.0, total_duration_s=250.0)  # 10 m/s
    plan = SplitPlanData(
        split_type="distance_km",
        split_value=1,
        rolling_target_mps=None,
        custom_splits=[(400.0, 5.0)],
    )
    result = AnalyzerV1().analyze(track, "distance_km", 1, split_plan=plan)
    splits = result["splits"]
    # 400m custom split, then two more 1000m rolling splits (2400m total of
    # the 2500m covered), all with no target past the first.
    assert [s["distance_m"] for s in splits] == pytest.approx([400.0, 1000.0, 1000.0], rel=0.001)
    assert splits[0]["target_speed_mps"] == 5.0
    for split in splits[1:]:
        assert split["target_speed_mps"] is None
        assert split["verdict"] is None


def test_rolling_plan_with_a_target_applies_it_to_every_split() -> None:
    track = _sparse_track(total_distance_m=2500.0, total_duration_s=250.0)  # 10 m/s
    plan = SplitPlanData(
        split_type="distance_km", split_value=1, rolling_target_mps=10.0, targets_as="speed"
    )
    result = AnalyzerV1().analyze(track, "distance_km", 1, split_plan=plan)
    splits = result["splits"]
    assert len(splits) == 2
    for split in splits:
        assert split["target_speed_mps"] == 10.0
        assert split["verdict"] == "on_target"
    assert result["split_targets_as"] == "speed"


def test_a_single_sparse_step_spanning_two_differently_sized_custom_splits() -> None:
    """Mirrors the existing multi-boundary regression tests above, but for a
    custom plan where the two boundaries crossed by one sparse step are
    different sizes (90s then 60s) — exactly the scenario
    docs/SPLIT-TARGETS-PLAN.md §2 calls out as easy to get wrong."""
    # 300m over 150s = 2 m/s throughout, crosses a 90s boundary (180m) then a
    # 60s boundary (150s total, exactly the far end of this single step).
    track = _sparse_track(total_distance_m=300.0, total_duration_s=150.0)
    plan = SplitPlanData(
        split_type="time_min",
        split_value=1,
        rolling_target_mps=None,
        custom_splits=[(90.0, 2.5), (60.0, 1.5)],
    )
    result = AnalyzerV1().analyze(track, "time_min", 1, split_plan=plan)
    splits = result["splits"]
    assert len(splits) == 2
    assert splits[0]["duration_seconds"] == pytest.approx(90.0, abs=0.5)
    assert splits[0]["target_speed_mps"] == 2.5
    assert splits[1]["duration_seconds"] == pytest.approx(60.0, abs=0.5)
    assert splits[1]["target_speed_mps"] == 1.5


def test_verdict_boundaries_at_exactly_plus_minus_five_percent() -> None:
    assert _verdict(5.0, 5.0) == "on_target"
    assert _verdict(5.249, 5.0) == "on_target"  # just inside +5%
    assert _verdict(5.25, 5.0) == "on_target"  # exactly +5%
    assert _verdict(5.251, 5.0) == "too_fast"  # just outside +5%
    assert _verdict(4.751, 5.0) == "on_target"  # just inside -5%
    assert _verdict(4.75, 5.0) == "on_target"  # exactly -5%
    assert _verdict(4.749, 5.0) == "too_slow"  # just outside -5%
    assert _verdict(5.0, None) is None


def test_no_split_plan_leaves_result_unchanged_from_before_issue_100() -> None:
    """Every split must still carry the new keys (target_speed_mps/verdict),
    both null, and split_targets_as must be null at the top level, so
    existing consumers of the result dict don't need to guard against a
    missing key — only a null value."""
    result = _analyze()
    assert result["split_targets_as"] is None
    for split in result["splits"]:
        assert split["target_speed_mps"] is None
        assert split["verdict"] is None


def _straight_line_track(
    *, n_points: int, step_m: float, step_s: float, ele: float | None = 100.0
) -> Track:
    """A straight line moving east, n_points fixes step_s apart, each
    step_m further along — used below to build a track with one bad leading
    point stitched onto an otherwise-clean run/ride."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    lon_per_meter = 1 / 111195
    points = [
        Point(
            lat=0.0,
            lon=i * step_m * lon_per_meter,
            ele=ele,
            time=start + timedelta(seconds=i * step_s),
        )
        for i in range(n_points)
    ]
    return Track(segments=[Segment(points=points)])


def test_a_stale_low_accuracy_leading_point_is_excluded_from_start_and_bounds() -> None:
    """Regression for issue #83: a real activity's very first GPS fix was a
    stale/cold fix ~5km from the true start, flagged by a sat:accuracy
    extension of 1000m (every other point was ~10m or better). The implied-
    speed check already excluded the *step* into it, but the point itself
    still became `start` and skewed `bounds` and the series' first speed
    sample. Points with poor accuracy must be dropped before any of that is
    derived, not just have their connecting step dropped."""
    track = _straight_line_track(n_points=20, step_m=3.0, step_s=1.0)
    bad_point = Point(
        lat=5.0, lon=5.0, ele=100.0, time=track.segments[0].points[0].time, accuracy_m=1000.0
    )
    stitched = Track(segments=[Segment(points=[bad_point, *track.segments[0].points])])

    result = AnalyzerV1().analyze(stitched)

    true_start = track.segments[0].points[0]
    assert result["start"] == {"lat": true_start.lat, "lon": true_start.lon}
    bounds = result["bounds"]
    assert bounds is not None
    assert bounds["max_lat"] < 1.0  # the bad point's lat=5.0 must not appear
    assert bounds["max_lon"] < 1.0  # the bad point's lon=5.0 must not appear
    # No huge speed spike in the series' first sample either.
    for sample in result["series"]:
        if sample["speed_mps"] is not None:
            assert sample["speed_mps"] < 50.0


def test_a_point_with_no_accuracy_data_is_never_dropped() -> None:
    """A GPX with no sat:accuracy extension at all (an old recording, a
    manually-uploaded/imported file) must analyze exactly as before — a
    missing accuracy is not evidence of a bad point, only an unmeasured one."""
    track = parse_gpx(_FIXTURE.read_bytes())
    assert all(p.accuracy_m is None for segment in track.segments for p in segment.points)
    result = AnalyzerV1().analyze(track)
    assert result["distance_meters"] == pytest.approx(_EXPECTED_DISTANCE_M, rel=0.01)


def test_cycling_activity_type_raises_the_implied_speed_cap() -> None:
    """Regression for issue #83: a cycling activity's genuine ~20 m/s (72
    km/h) descent used to be misclassified as a GPS jump under the
    running-only 12.5 m/s cap, breaking the step chain mid-ride. Passing
    activity_type="cycling" should accept it as real motion."""
    track = _straight_line_track(n_points=10, step_m=20.0, step_s=1.0)  # 20 m/s throughout

    running_result = AnalyzerV1().analyze(track, activity_type="running")
    cycling_result = AnalyzerV1().analyze(track, activity_type="cycling")

    # Under the running cap, every step is an implausible jump and gets
    # dropped, so distance collapses to ~0.
    assert running_result["distance_meters"] < 5.0
    # Under the cycling cap, the same steps are accepted as real motion.
    assert cycling_result["distance_meters"] == pytest.approx(9 * 20.0, rel=0.01)


def test_walking_activity_type_uses_the_same_cap_as_running() -> None:
    """Issue #129: walking is a distinct activity_type tag from running, but
    deliberately shares its implied-speed cap — same physiological limits."""
    track = _straight_line_track(n_points=10, step_m=20.0, step_s=1.0)  # 20 m/s throughout

    running_result = AnalyzerV1().analyze(track, activity_type="running")
    walking_result = AnalyzerV1().analyze(track, activity_type="walking")

    assert walking_result["distance_meters"] == pytest.approx(running_result["distance_meters"])


def test_unknown_activity_type_falls_back_to_the_running_cap() -> None:
    """A future/unrecognised activity_type string must not silently disable
    jump rejection — falls back to the conservative running threshold."""
    track = _straight_line_track(n_points=10, step_m=20.0, step_s=1.0)  # 20 m/s throughout
    result = AnalyzerV1().analyze(track, activity_type="swimming")
    assert result["distance_meters"] < 5.0
