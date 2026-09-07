"""R8 in docs/SERVER-PRODUCTION-PLAN.md: reject GPX input carrying a DOCTYPE
or ENTITY declaration, which GPX never legitimately needs."""

import pytest

from app.analysis.gpx_parser import GpxParseError, parse_gpx

_VALID_TRKPT = (
    b'<?xml version="1.0"?><gpx version="1.1"><trk><trkseg>'
    b'<trkpt lat="0" lon="0"><time>2026-01-01T00:00:00Z</time></trkpt>'
    b'<trkpt lat="0.001" lon="0"><time>2026-01-01T00:00:01Z</time></trkpt>'
    b"</trkseg></trk></gpx>"
)


def test_valid_gpx_still_parses() -> None:
    track = parse_gpx(_VALID_TRKPT)
    assert track.point_count == 2


@pytest.mark.parametrize(
    "declaration",
    [
        b'<!DOCTYPE gpx [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>',
        b"<!DOCTYPE gpx>",
        b'<!ENTITY xxe "test">',
    ],
)
def test_doctype_or_entity_declaration_is_rejected(declaration: bytes) -> None:
    poisoned = b'<?xml version="1.0"?>' + declaration + _VALID_TRKPT.split(b"?>", 1)[1]
    with pytest.raises(GpxParseError):
        parse_gpx(poisoned)


# docs/GPS-METRICS-PLAN.md step 1: the mobile app now writes per-point
# accuracy/speed diagnostics as <sat:...> GPX extensions (see
# mobile/lib/core/files/run_gpx_log.dart). This is the "server still parses
# these files" check the plan calls for — parse_gpx must keep ignoring
# unknown extensions rather than choking on them.
_TRKPT_WITH_EXTENSIONS = (
    b'<?xml version="1.0"?>'
    b'<gpx version="1.1" xmlns:sat="https://simple-activity-tracker.local/gpx-extensions">'
    b"<trk><trkseg>"
    b'<trkpt lat="0" lon="0"><time>2026-01-01T00:00:00Z</time>'
    b"<extensions>"
    b"<sat:accuracy>12.5</sat:accuracy>"
    b"<sat:has_accuracy>true</sat:has_accuracy>"
    b"<sat:speed>1.7</sat:speed>"
    b"<sat:has_speed>true</sat:has_speed>"
    b"</extensions>"
    b"</trkpt>"
    b'<trkpt lat="0.001" lon="0"><time>2026-01-01T00:00:01Z</time>'
    b"<extensions>"
    b"<sat:accuracy>40.0</sat:accuracy>"
    b"<sat:has_accuracy>false</sat:has_accuracy>"
    b"<sat:has_speed>false</sat:has_speed>"
    b"</extensions>"
    b"</trkpt>"
    b"</trkseg></trk></gpx>"
)


def test_unknown_extensions_are_ignored() -> None:
    track = parse_gpx(_TRKPT_WITH_EXTENSIONS)
    assert track.point_count == 2
    points = track.segments[0].points
    assert (points[0].lat, points[0].lon) == (0, 0)
    assert (points[1].lat, points[1].lon) == (0.001, 0)
