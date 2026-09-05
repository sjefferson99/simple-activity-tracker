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
