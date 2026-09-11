from datetime import UTC

import fitparse

from app.analysis.track import Point, Segment, Track

_SEMICIRCLES_TO_DEGREES = 180 / 2**31


class FitParseError(Exception):
    pass


class FitNoTrackPointsError(FitParseError):
    """Raised specifically when parsing succeeded but the file has zero
    usable (timestamped + positioned) record messages — most commonly a
    genuinely GPS-less indoor/virtual activity, not a corrupt file. See
    GpxNoTrackPointsError's docstring in gpx_parser.py for why this is its
    own subclass."""


def parse_fit(data: bytes) -> Track:
    """Parses FIT (Garmin/ANT binary) bytes into a Track, using the fitparse
    library (unlike GPX/TCX, FIT's binary framing makes hand-rolling
    impractical). Mirrors parse_gpx/parse_tcx's contract: "record" messages
    missing a position are dropped (real Strava FIT exports have been
    observed with an initial timestamp-only record before GPS lock, same as
    TCX's positionless trackpoints), and FitParseError is raised if nothing
    usable remains.

    FIT stores lat/lon as 32-bit "semicircles" (int32 where 2**31
    semicircles = 180 degrees), not degrees directly — must be converted.
    FIT has both a legacy `altitude` and a GPS-derived `enhanced_altitude`
    field on newer devices; enhanced_altitude is preferred when present.

    FIT doesn't have GPX's multi-<trkseg>/TCX's multi-<Track> concept in the
    same way (session/lap messages exist but don't map cleanly to Segment
    boundaries for this app's purposes) — every record message in the file
    becomes one Segment, in file order.
    """
    try:
        fitfile = fitparse.FitFile(data)
        points: list[Point] = []
        for record in fitfile.get_messages("record"):
            fields = {f.name: f.value for f in record}
            lat_semi = fields.get("position_lat")
            lon_semi = fields.get("position_long")
            time = fields.get("timestamp")
            if lat_semi is None or lon_semi is None or time is None:
                continue
            ele = fields.get("enhanced_altitude")
            if ele is None:
                ele = fields.get("altitude")
            points.append(
                Point(
                    lat=lat_semi * _SEMICIRCLES_TO_DEGREES,
                    lon=lon_semi * _SEMICIRCLES_TO_DEGREES,
                    ele=ele,
                    time=time if time.tzinfo is not None else time.replace(tzinfo=UTC),
                )
            )
    except fitparse.FitParseError as exc:
        raise FitParseError(f"Could not parse FIT: {exc}") from exc

    track = Track(segments=[Segment(points=points)] if points else [])
    if track.point_count == 0:
        raise FitNoTrackPointsError("FIT file has no timestamped, positioned record messages")
    return track
