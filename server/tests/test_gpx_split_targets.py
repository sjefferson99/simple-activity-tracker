"""Issue #99: the mobile app writes three additional root <extensions>
elements alongside sat:split_type/sat:split_value once a run has split
targets or a custom plan — sat:split_target, sat:split_plan, and
sat:split_targets_as (see mobile's RunGpxLog and
docs/SPLIT-TARGETS-PLAN.md §4.2). The server does not use them yet (that is
issue #100's job); this proves parse_split_preference and parse_gpx keep
behaving exactly as they do for a GPX with none of them, i.e. the new
extensions are genuinely ignored rather than accidentally tripping something
(a stricter schema, an unexpected key collision, etc.)."""

from app.analysis.gpx_parser import parse_gpx, parse_split_preference

_NS = "https://simple-activity-tracker.local/gpx-extensions"

_TRK = (
    b'<trk><trkseg><trkpt lat="0" lon="0"><time>2026-01-01T00:00:00Z</time></trkpt>'
    b'<trkpt lat="0.001" lon="0"><time>2026-01-01T00:00:01Z</time></trkpt>'
    b"</trkseg></trk>"
)


def _gpx(extensions_xml: bytes) -> bytes:
    return (
        b'<?xml version="1.0"?><gpx version="1.1" '
        b'xmlns:sat="' + _NS.encode() + b'">' + extensions_xml + _TRK + b"</gpx>"
    )


def test_split_target_alongside_split_type_value_parses_the_same_preference() -> None:
    gpx = _gpx(
        b"<extensions><sat:split_type>distance_km</sat:split_type>"
        b"<sat:split_value>1</sat:split_value>"
        b"<sat:split_target>2.222</sat:split_target>"
        b"<sat:split_targets_as>pace</sat:split_targets_as></extensions>"
    )
    assert parse_split_preference(gpx) == ("distance_km", 1)


def test_split_plan_alongside_split_type_value_parses_the_same_preference() -> None:
    gpx = _gpx(
        b"<extensions><sat:split_type>time_min</sat:split_type>"
        b"<sat:split_value>1</sat:split_value>"
        b"<sat:split_plan>90@2.222;60@1.667;120</sat:split_plan>"
        b"<sat:split_targets_as>speed</sat:split_targets_as></extensions>"
    )
    assert parse_split_preference(gpx) == ("time_min", 1)


def test_split_targets_as_alone_does_not_change_the_parsed_preference() -> None:
    gpx = _gpx(
        b"<extensions><sat:split_type>distance_mi</sat:split_type>"
        b"<sat:split_value>3</sat:split_value>"
        b"<sat:split_targets_as>speed</sat:split_targets_as></extensions>"
    )
    assert parse_split_preference(gpx) == ("distance_mi", 3)


def test_parse_gpx_still_reads_the_same_track_points_and_ignores_the_new_extensions() -> None:
    plain = _gpx(
        b"<extensions><sat:split_type>distance_km</sat:split_type>"
        b"<sat:split_value>1</sat:split_value></extensions>"
    )
    with_targets = _gpx(
        b"<extensions><sat:split_type>distance_km</sat:split_type>"
        b"<sat:split_value>1</sat:split_value>"
        b"<sat:split_target>3.0</sat:split_target>"
        b"<sat:split_plan>400@3;200</sat:split_plan>"
        b"<sat:split_targets_as>pace</sat:split_targets_as></extensions>"
    )

    plain_track = parse_gpx(plain)
    targets_track = parse_gpx(with_targets)

    assert len(targets_track.segments) == len(plain_track.segments)
    assert len(targets_track.segments[0].points) == len(plain_track.segments[0].points)
    for plain_point, targets_point in zip(
        plain_track.segments[0].points, targets_track.segments[0].points, strict=True
    ):
        assert plain_point.lat == targets_point.lat
        assert plain_point.lon == targets_point.lon
        assert plain_point.time == targets_point.time
