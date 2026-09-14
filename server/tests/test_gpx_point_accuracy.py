"""parse_gpx's per-trackpoint sat:accuracy/sat:has_accuracy extensions
(issue #83) — written by mobile's RunGpxLog, read here so AnalyzerV1 and the
map's sample_track can drop a stale/low-accuracy fix rather than let it
poison start/bounds/distance."""

from app.analysis.gpx_parser import parse_gpx

_NS = "https://simple-activity-tracker.local/gpx-extensions"
_GPX_OPEN = b'<?xml version="1.0"?><gpx version="1.1" xmlns:sat="' + _NS.encode() + b'">'


def _trkpt(lat: str, lon: str, time: str, extensions_xml: bytes = b"") -> bytes:
    return (
        f'<trkpt lat="{lat}" lon="{lon}"><time>{time}</time>'.encode()
        + extensions_xml
        + b"</trkpt>"
    )


def _gpx(points_xml: bytes) -> bytes:
    return _GPX_OPEN + b"<trk><trkseg>" + points_xml + b"</trkseg></trk></gpx>"


def test_reads_accuracy_value() -> None:
    gpx = _gpx(
        _trkpt(
            "0",
            "0",
            "2026-01-01T00:00:00Z",
            b"<extensions><sat:accuracy>7.5</sat:accuracy>"
            b"<sat:has_accuracy>true</sat:has_accuracy></extensions>",
        )
    )
    track = parse_gpx(gpx)
    assert track.segments[0].points[0].accuracy_m == 7.5


def test_has_accuracy_false_means_unmeasured_not_zero() -> None:
    gpx = _gpx(
        _trkpt(
            "0",
            "0",
            "2026-01-01T00:00:00Z",
            b"<extensions><sat:accuracy>0.0</sat:accuracy>"
            b"<sat:has_accuracy>false</sat:has_accuracy></extensions>",
        )
    )
    track = parse_gpx(gpx)
    assert track.segments[0].points[0].accuracy_m is None


def test_missing_extensions_leaves_accuracy_none() -> None:
    gpx = _gpx(_trkpt("0", "0", "2026-01-01T00:00:00Z"))
    track = parse_gpx(gpx)
    assert track.segments[0].points[0].accuracy_m is None


def test_unparseable_accuracy_value_leaves_accuracy_none() -> None:
    gpx = _gpx(
        _trkpt(
            "0",
            "0",
            "2026-01-01T00:00:00Z",
            b"<extensions><sat:accuracy>not-a-number</sat:accuracy>"
            b"<sat:has_accuracy>true</sat:has_accuracy></extensions>",
        )
    )
    track = parse_gpx(gpx)
    assert track.segments[0].points[0].accuracy_m is None
