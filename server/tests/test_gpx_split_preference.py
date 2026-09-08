"""parse_split_preference (issue #43): best-effort split preference read from
the uploaded GPX's root <extensions>, written by mobile's RunGpxLog."""

from app.analysis.gpx_parser import parse_split_preference

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


def test_reads_distance_km_extension() -> None:
    gpx = _gpx(
        b"<extensions><sat:split_type>distance_km</sat:split_type>"
        b"<sat:split_value>1</sat:split_value></extensions>"
    )
    assert parse_split_preference(gpx) == ("distance_km", 1)


def test_reads_distance_mi_extension() -> None:
    gpx = _gpx(
        b"<extensions><sat:split_type>distance_mi</sat:split_type>"
        b"<sat:split_value>1</sat:split_value></extensions>"
    )
    assert parse_split_preference(gpx) == ("distance_mi", 1)


def test_reads_time_min_extension_with_larger_value() -> None:
    gpx = _gpx(
        b"<extensions><sat:split_type>time_min</sat:split_type>"
        b"<sat:split_value>5</sat:split_value></extensions>"
    )
    assert parse_split_preference(gpx) == ("time_min", 5)


def test_returns_none_when_no_extensions_present() -> None:
    gpx = _gpx(b"")
    assert parse_split_preference(gpx) is None


def test_returns_none_for_invalid_split_type() -> None:
    gpx = _gpx(
        b"<extensions><sat:split_type>bogus</sat:split_type>"
        b"<sat:split_value>1</sat:split_value></extensions>"
    )
    assert parse_split_preference(gpx) is None


def test_returns_none_for_non_integer_split_value() -> None:
    gpx = _gpx(
        b"<extensions><sat:split_type>distance_km</sat:split_type>"
        b"<sat:split_value>abc</sat:split_value></extensions>"
    )
    assert parse_split_preference(gpx) is None


def test_returns_none_for_non_positive_split_value() -> None:
    gpx = _gpx(
        b"<extensions><sat:split_type>distance_km</sat:split_type>"
        b"<sat:split_value>0</sat:split_value></extensions>"
    )
    assert parse_split_preference(gpx) is None


def test_returns_none_when_split_value_missing() -> None:
    gpx = _gpx(b"<extensions><sat:split_type>distance_km</sat:split_type></extensions>")
    assert parse_split_preference(gpx) is None


def test_returns_none_for_unparseable_gpx() -> None:
    assert parse_split_preference(b"this is not gpx") is None


def test_returns_none_for_doctype_declaration() -> None:
    gpx = (
        b'<?xml version="1.0"?><!DOCTYPE gpx><gpx version="1.1" '
        b'xmlns:sat="' + _NS.encode() + b'">'
        b"<extensions><sat:split_type>distance_km</sat:split_type>"
        b"<sat:split_value>1</sat:split_value></extensions>" + _TRK + b"</gpx>"
    )
    assert parse_split_preference(gpx) is None
