"""Downsamples a parsed Track to at most `max_points` per segment, for the
map view — see R8 in docs/SERVER-PRODUCTION-PLAN.md. Pure function so the
same downsampled shape can be cached at upload/reanalyze time (the common
case: a client asking for the default max_points) and computed on the fly
for a non-default request, without duplicating the sampling logic."""

from typing import Any

from app.analysis.track import Track

DEFAULT_MAX_POINTS = 2000


def sample_track(track: Track, *, max_points: int) -> dict[str, Any]:
    """Returns {"segments": [[{"lat", "lon", "ele", "t"}, ...], ...]} — the
    same shape as the API's TrackOut/TrackPointOut, but as plain dicts so it
    can be stored as JSON and re-served without re-parsing the GPX. `t` on
    every point is relative to the first point of the first segment, so a
    gap between segments (e.g. a pause/resume) is reflected in later
    segments' timestamps rather than each segment restarting at zero."""
    out_segments: list[list[dict[str, Any]]] = []
    start_time = track.segments[0].points[0].time
    for segment in track.segments:
        points = segment.points
        stride = max(1, -(-len(points) // max_points))
        sampled = points[::stride]
        if sampled[-1] is not points[-1]:
            sampled.append(points[-1])
        out_segments.append(
            [
                {
                    "lat": p.lat,
                    "lon": p.lon,
                    "ele": p.ele,
                    "t": (p.time - start_time).total_seconds(),
                }
                for p in sampled
            ]
        )
    return {"segments": out_segments}
