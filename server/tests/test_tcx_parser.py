"""tcx_parser.py — TCX (Garmin Training Center v2) parsing, per PR 2 of
issue #61's Strava-import plan. Mirrors test_gpx_parser_hardening.py's XXE
tests for the same rationale (R8 in docs/SERVER-PRODUCTION-PLAN.md)."""

import pytest

from app.analysis.tcx_parser import TcxParseError, parse_tcx

_VALID_TCX = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">'
    b'<Activities><Activity Sport="Running"><Id>2026-01-01T00:00:00Z</Id>'
    b'<Lap StartTime="2026-01-01T00:00:00Z"><Track>'
    b"<Trackpoint><Time>2026-01-01T00:00:00Z</Time>"
    b"<Position><LatitudeDegrees>0</LatitudeDegrees><LongitudeDegrees>0</LongitudeDegrees></Position>"
    b"<AltitudeMeters>10.5</AltitudeMeters></Trackpoint>"
    b"<Trackpoint><Time>2026-01-01T00:00:01Z</Time>"
    b"<Position><LatitudeDegrees>0.001</LatitudeDegrees><LongitudeDegrees>0</LongitudeDegrees></Position>"
    b"</Trackpoint>"
    b"</Track></Lap></Activity></Activities></TrainingCenterDatabase>"
)


def test_valid_tcx_parses() -> None:
    track = parse_tcx(_VALID_TCX)
    assert track.point_count == 2
    points = track.segments[0].points
    assert (points[0].lat, points[0].lon, points[0].ele) == (0, 0, 10.5)
    assert points[1].ele is None


# Real Strava TCX exports have been observed with Trackpoints that carry a
# <Time> but no <Position> (an HR-only sample before GPS lock) — these must
# be dropped, same as a missing time, rather than crashing on a None lat/lon.
_TCX_WITH_POSITIONLESS_POINT = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">'
    b'<Activities><Activity Sport="Ride"><Id>2026-01-01T00:00:00Z</Id>'
    b'<Lap StartTime="2026-01-01T00:00:00Z"><Track>'
    b"<Trackpoint><Time>2026-01-01T00:00:00Z</Time>"
    b"<HeartRateBpm><Value>85</Value></HeartRateBpm></Trackpoint>"
    b"<Trackpoint><Time>2026-01-01T00:00:01Z</Time>"
    b"<Position><LatitudeDegrees>1</LatitudeDegrees><LongitudeDegrees>1</LongitudeDegrees></Position>"
    b"</Trackpoint>"
    b"</Track></Lap></Activity></Activities></TrainingCenterDatabase>"
)


def test_positionless_trackpoint_is_dropped() -> None:
    track = parse_tcx(_TCX_WITH_POSITIONLESS_POINT)
    assert track.point_count == 1
    assert track.segments[0].points[0].lat == 1


_TCX_NO_TRACKPOINTS = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">'
    b'<Activities><Activity Sport="Ride"><Id>2026-01-01T00:00:00Z</Id>'
    b'<Lap StartTime="2026-01-01T00:00:00Z"><Track></Track></Lap></Activity>'
    b"</Activities></TrainingCenterDatabase>"
)


def test_zero_usable_points_raises() -> None:
    with pytest.raises(TcxParseError):
        parse_tcx(_TCX_NO_TRACKPOINTS)


def test_multiple_tracks_become_multiple_segments() -> None:
    data = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">'
        b'<Activities><Activity Sport="Ride"><Id>2026-01-01T00:00:00Z</Id>'
        b'<Lap StartTime="2026-01-01T00:00:00Z"><Track>'
        b"<Trackpoint><Time>2026-01-01T00:00:00Z</Time>"
        b"<Position><LatitudeDegrees>0</LatitudeDegrees><LongitudeDegrees>0</LongitudeDegrees></Position>"
        b"</Trackpoint></Track></Lap>"
        b'<Lap StartTime="2026-01-01T00:05:00Z"><Track>'
        b"<Trackpoint><Time>2026-01-01T00:05:00Z</Time>"
        b"<Position><LatitudeDegrees>1</LatitudeDegrees><LongitudeDegrees>1</LongitudeDegrees></Position>"
        b"</Trackpoint></Track></Lap>"
        b"</Activity></Activities></TrainingCenterDatabase>"
    )
    track = parse_tcx(data)
    assert len(track.segments) == 2
    assert track.point_count == 2


def test_malformed_xml_raises() -> None:
    with pytest.raises(TcxParseError):
        parse_tcx(b"<not><valid")


def test_non_utf8_bytes_raise() -> None:
    with pytest.raises(TcxParseError):
        parse_tcx(b"\xff\xfe\x00\x01")


@pytest.mark.parametrize(
    "declaration",
    [
        b'<!DOCTYPE TrainingCenterDatabase [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>',
        b"<!DOCTYPE TrainingCenterDatabase>",
        b'<!ENTITY xxe "test">',
    ],
)
def test_doctype_or_entity_declaration_is_rejected(declaration: bytes) -> None:
    poisoned = b'<?xml version="1.0"?>' + declaration + _VALID_TCX.split(b"?>", 1)[1]
    with pytest.raises(TcxParseError):
        parse_tcx(poisoned)
