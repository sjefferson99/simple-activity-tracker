import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import defusedxml.ElementTree as DefusedET
from defusedxml.common import DefusedXmlException

from app.analysis.track import Point, Segment, Track


class TcxParseError(Exception):
    pass


class TcxNoTrackPointsError(TcxParseError):
    """Raised specifically when parsing succeeded but the file has zero
    usable (timestamped + positioned) points — see GpxNoTrackPointsError's
    docstring in gpx_parser.py for why this is its own subclass."""


def parse_tcx(data: bytes) -> Track:
    """Parses TCX (Garmin Training Center v2) bytes into a Track. Mirrors
    parse_gpx's contract: points missing a usable time or position are
    dropped, and GpxParseError's TCX equivalent is raised if nothing usable
    remains. TCX only needs a handful of fields out of a much larger schema
    (laps, HR, cadence, power — all discarded, per issue #61), so this is
    hand-rolled against defusedxml's drop-in ElementTree replacement (guards
    against XXE/entity-expansion attacks structurally, not just via the
    DOCTYPE/ENTITY substring check below) rather than pulling in a
    third-party TCX-specific library. One Segment per <Track> element (TCX's
    closest equivalent to GPX's <trkseg>), matching gpx_parser.py's
    one-Segment-per-<trkseg> rule.

    Real Strava TCX exports have been observed with Trackpoints that carry a
    <Time> but no <Position> at all (e.g. an early HR-only sample before GPS
    lock) — these are dropped the same as a missing time, since a Point with
    no lat/lon can't be part of a Track.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TcxParseError("TCX file is not valid UTF-8") from exc

    # Same explicit rejection as gpx_parser.py (see R8 in
    # docs/SERVER-PRODUCTION-PLAN.md) — belt-and-suspenders on top of
    # defusedxml's structural protection below.
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise TcxParseError("TCX file must not contain a DOCTYPE or ENTITY declaration")

    try:
        root = DefusedET.fromstring(text)
    except (ET.ParseError, DefusedXmlException) as exc:
        # DefusedXmlException covers the actual XXE-style attacks (entity
        # expansion, external references) defusedxml blocks structurally —
        # a real one raises here even though the DOCTYPE/ENTITY substring
        # check above already ought to have rejected it (belt-and-suspenders
        # both ways), and ET.ParseError covers plain malformed XML.
        raise TcxParseError(f"Could not parse TCX: {exc}") from exc

    segments: list[Segment] = []
    # {*} wildcard-namespace matching (ElementTree, Python 3.8+) rather than
    # hardcoding the exact TrainingCenterDatabase namespace URI/version,
    # since Garmin's schema has varied slightly across TCX producers.
    # Note: Element.iter() does NOT support the {*} wildcard (silently
    # matches nothing) — only find()/findall() do, so this must use
    # findall(".//...") rather than the more natural-looking iter().
    for track_el in root.findall(".//{*}Track"):
        points: list[Point] = []
        for tp_el in track_el.findall("{*}Trackpoint"):
            time = _parse_time(tp_el.findtext("{*}Time"))
            if time is None:
                continue
            pos_el = tp_el.find("{*}Position")
            if pos_el is None:
                continue
            lat = _parse_float(pos_el.findtext("{*}LatitudeDegrees"))
            lon = _parse_float(pos_el.findtext("{*}LongitudeDegrees"))
            if lat is None or lon is None:
                continue
            ele = _parse_float(tp_el.findtext("{*}AltitudeMeters"))
            points.append(Point(lat=lat, lon=lon, ele=ele, time=time))
        if points:
            segments.append(Segment(points=points))

    track = Track(segments=segments)
    if track.point_count == 0:
        raise TcxNoTrackPointsError("TCX file has no timestamped, positioned track points")
    return track


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # TCX timestamps are ISO 8601 with a "Z" suffix; fromisoformat needs
        # "+00:00" instead prior to Python 3.11, so normalize explicitly
        # rather than relying on the runtime's version-dependent leniency.
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
