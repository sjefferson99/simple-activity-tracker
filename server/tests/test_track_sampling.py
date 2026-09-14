from datetime import UTC, datetime

from app.analysis.track import Point, Segment, Track
from app.analysis.track_sampling import sample_track


def test_a_low_accuracy_point_is_excluded_from_the_sampled_track() -> None:
    """Regression for issue #83: a stale/cold GPS fix (reported via
    sat:accuracy) used to still appear as a stray point on the map, even
    though AnalyzerV1 already excludes the implausible step into it — the map
    reads the raw sampled track, not AnalyzerV1's steps."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bad = Point(lat=50.0, lon=50.0, ele=None, time=start, accuracy_m=1000.0)
    good = [Point(lat=0.0, lon=0.001 * i, ele=None, time=start, accuracy_m=5.0) for i in range(5)]
    track = Track(segments=[Segment(points=[bad, *good])])

    sampled = sample_track(track, max_points=100)

    lats = [p["lat"] for p in sampled["segments"][0]]
    assert 50.0 not in lats


def test_a_segment_with_no_accurate_points_falls_back_to_the_original_points() -> None:
    """If every point in a segment fails the accuracy check, filtering must
    not empty it out entirely — keep the original points rather than produce
    a segment with zero samples."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    points = [Point(lat=0.0, lon=0.0, ele=None, time=start, accuracy_m=1000.0)]
    track = Track(segments=[Segment(points=points)])

    sampled = sample_track(track, max_points=100)

    assert len(sampled["segments"][0]) == 1


def test_points_with_no_accuracy_data_are_all_kept() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    points = [Point(lat=0.0, lon=0.001 * i, ele=None, time=start) for i in range(5)]
    track = Track(segments=[Segment(points=points)])

    sampled = sample_track(track, max_points=100)

    assert len(sampled["segments"][0]) == 5
