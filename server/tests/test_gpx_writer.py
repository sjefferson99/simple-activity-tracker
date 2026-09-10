from datetime import UTC, datetime

from app.analysis.gpx_parser import parse_gpx
from app.analysis.gpx_writer import track_to_gpx_bytes
from app.analysis.track import Point, Segment, Track


def _sample_track() -> Track:
    t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)
    return Track(
        segments=[
            Segment(
                points=[
                    Point(lat=51.5, lon=-0.1, ele=12.5, time=t0),
                    Point(lat=51.501, lon=-0.101, ele=None, time=t1),
                ]
            )
        ]
    )


def test_track_to_gpx_bytes_round_trips_through_parse_gpx() -> None:
    track = _sample_track()
    gpx_bytes = track_to_gpx_bytes(track)
    reparsed = parse_gpx(gpx_bytes)

    assert reparsed.point_count == track.point_count
    original = track.segments[0].points
    round_tripped = reparsed.segments[0].points
    for orig, rt in zip(original, round_tripped, strict=True):
        assert orig.lat == rt.lat
        assert orig.lon == rt.lon
        assert orig.ele == rt.ele
        assert orig.time == rt.time


def test_track_to_gpx_bytes_preserves_multiple_segments() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    track = Track(
        segments=[
            Segment(points=[Point(lat=0, lon=0, ele=None, time=t0)]),
            Segment(points=[Point(lat=1, lon=1, ele=None, time=t0)]),
        ]
    )
    reparsed = parse_gpx(track_to_gpx_bytes(track))
    assert len(reparsed.segments) == 2


def test_track_to_gpx_bytes_sets_creator() -> None:
    gpx_bytes = track_to_gpx_bytes(_sample_track(), creator="test-creator")
    assert b'creator="test-creator"' in gpx_bytes
