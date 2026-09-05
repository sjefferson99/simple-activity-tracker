from datetime import UTC, datetime

import gpxpy
import gpxpy.gpx

from app.analysis.track import Point, Segment, Track


class GpxParseError(Exception):
    pass


def parse_gpx(data: bytes) -> Track:
    """Parses GPX bytes into a Track. Points with no timestamp are dropped —
    a Track without complete timing can't support any of the analysis this
    module does (splits, speed, moving time). Raises GpxParseError on
    anything gpxpy itself rejects, or if there's not a single usable point,
    so callers can map both to a 400 without inspecting gpxpy's exceptions.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GpxParseError("GPX file is not valid UTF-8") from exc

    # GPX never legitimately needs a DOCTYPE or a custom entity declaration —
    # reject both outright rather than relying solely on the stdlib expat
    # parser's own protections (billion-laughs is blocked in modern Python,
    # but external entity resolution history is worth not depending on). See
    # R8 in docs/SERVER-PRODUCTION-PLAN.md.
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise GpxParseError("GPX file must not contain a DOCTYPE or ENTITY declaration")

    try:
        gpx = gpxpy.parse(text)
    except Exception as exc:  # gpxpy raises its own GPXException plus XML errors
        raise GpxParseError(f"Could not parse GPX: {exc}") from exc

    segments: list[Segment] = []
    for gpx_track in gpx.tracks:
        for gpx_segment in gpx_track.segments:
            points = [
                Point(
                    lat=p.latitude,
                    lon=p.longitude,
                    ele=p.elevation,
                    time=_as_utc(p.time),
                )
                for p in gpx_segment.points
                if p.time is not None
            ]
            if points:
                segments.append(Segment(points=points))

    track = Track(segments=segments)
    if track.point_count == 0:
        raise GpxParseError("GPX file has no timestamped track points")
    return track


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def guess_device_name(data: bytes) -> str | None:
    """Best-effort device name for a manually-uploaded GPX, read from the
    root <gpx creator="..."> attribute (what Garmin/most standalone trackers
    set — e.g. "Foretrex 401") or the <metadata><author><name> as a fallback.
    Never raises: this is only ever used to prefill an editable form field,
    so a file gpxpy can't even parse just yields no suggestion rather than
    failing the whole upload (parse_gpx already does the real validation).
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        return None
    try:
        gpx = gpxpy.parse(text)
    except Exception:
        return None

    creator = (gpx.creator or "").strip()
    if creator:
        return creator
    author = (gpx.author_name or "").strip()
    return author or None
