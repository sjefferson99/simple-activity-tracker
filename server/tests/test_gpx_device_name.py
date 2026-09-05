"""guess_device_name (issue #38): best-effort device name for a manually
uploaded GPX, read from <gpx creator="..."> or <metadata><author><name>."""

from app.analysis.gpx_parser import guess_device_name

_TRK = (
    b'<trk><trkseg><trkpt lat="0" lon="0"><time>2026-01-01T00:00:00Z</time></trkpt>'
    b'<trkpt lat="0.001" lon="0"><time>2026-01-01T00:00:01Z</time></trkpt>'
    b"</trkseg></trk>"
)


def test_reads_creator_attribute() -> None:
    gpx = b'<?xml version="1.0"?><gpx version="1.1" creator="Foretrex 401">' + _TRK + b"</gpx>"
    assert guess_device_name(gpx) == "Foretrex 401"


def test_falls_back_to_author_name_when_no_creator() -> None:
    gpx = (
        b'<?xml version="1.0"?><gpx version="1.1">'
        b"<metadata><author><name>Some Watch</name></author></metadata>" + _TRK + b"</gpx>"
    )
    assert guess_device_name(gpx) == "Some Watch"


def test_returns_none_when_neither_present() -> None:
    gpx = b'<?xml version="1.0"?><gpx version="1.1">' + _TRK + b"</gpx>"
    assert guess_device_name(gpx) is None


def test_returns_none_for_unparseable_gpx() -> None:
    assert guess_device_name(b"this is not gpx") is None


def test_returns_none_for_doctype_declaration() -> None:
    gpx = (
        b'<?xml version="1.0"?><!DOCTYPE gpx><gpx version="1.1" creator="Evil">' + _TRK + b"</gpx>"
    )
    assert guess_device_name(gpx) is None
