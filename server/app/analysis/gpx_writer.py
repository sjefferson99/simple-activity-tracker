import gpxpy.gpx

from app.analysis.track import Track


def track_to_gpx_bytes(track: Track, creator: str = "simple-activity-tracker") -> bytes:
    """Serializes a Track back to GPX bytes — the inverse of parse_gpx(). Used
    to convert non-GPX import sources (TCX, FIT) to GPX at import time, so
    the blob store's .gpx convention and every existing GPX-consuming code
    path (AnalyzerV1, download, export) need no format-awareness. Round-trips
    through gpxpy (the same library gpx_parser.py reads with) rather than
    hand-rolling XML, so the output is guaranteed valid input to parse_gpx()
    again."""
    gpx = gpxpy.gpx.GPX()
    gpx.creator = creator
    for segment in track.segments:
        gpx_track = gpxpy.gpx.GPXTrack()
        gpx.tracks.append(gpx_track)
        gpx_segment = gpxpy.gpx.GPXTrackSegment()
        gpx_track.segments.append(gpx_segment)
        for point in segment.points:
            gpx_segment.points.append(
                gpxpy.gpx.GPXTrackPoint(
                    latitude=point.lat,
                    longitude=point.lon,
                    elevation=point.ele,
                    time=point.time,
                )
            )
    return gpx.to_xml().encode("utf-8")
