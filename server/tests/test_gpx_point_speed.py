"""parse_gpx's per-trackpoint sat:speed/sat:has_speed extensions (issue #50)
— written by mobile's RunGpxLog, read here so AnalyzerV1 can credit distance
from the GPS chip's own Doppler speed instead of summing position deltas
(see app/analysis/v1.py's _credited_distance and ANALYSIS_VERSION note)."""

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


def test_reads_speed_value() -> None:
    gpx = _gpx(
        _trkpt(
            "0",
            "0",
            "2026-01-01T00:00:00Z",
            b"<extensions><sat:speed>1.7</sat:speed>"
            b"<sat:has_speed>true</sat:has_speed></extensions>",
        )
    )
    track = parse_gpx(gpx)
    assert track.segments[0].points[0].speed_mps == 1.7


def test_has_speed_false_means_unmeasured_not_zero() -> None:
    gpx = _gpx(
        _trkpt(
            "0",
            "0",
            "2026-01-01T00:00:00Z",
            b"<extensions><sat:has_speed>false</sat:has_speed></extensions>",
        )
    )
    track = parse_gpx(gpx)
    assert track.segments[0].points[0].speed_mps is None


def test_missing_extensions_leaves_speed_none() -> None:
    gpx = _gpx(_trkpt("0", "0", "2026-01-01T00:00:00Z"))
    track = parse_gpx(gpx)
    assert track.segments[0].points[0].speed_mps is None


def test_unparseable_speed_value_leaves_speed_none() -> None:
    gpx = _gpx(
        _trkpt(
            "0",
            "0",
            "2026-01-01T00:00:00Z",
            b"<extensions><sat:speed>not-a-number</sat:speed>"
            b"<sat:has_speed>true</sat:has_speed></extensions>",
        )
    )
    track = parse_gpx(gpx)
    assert track.segments[0].points[0].speed_mps is None
