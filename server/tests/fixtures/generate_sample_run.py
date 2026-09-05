"""Generates tests/fixtures/sample_run.gpx: a synthetic 3km run at a
constant 5:00 min/km pace, with known-in-advance answers for distance,
moving time, splits, and elevation gain — see docs/WEB-PLAN.md W1 step 3.

Run with: uv run python tests/fixtures/generate_sample_run.py
"""

import math
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import gpxpy
import gpxpy.gpx

_START = datetime(2026, 1, 1, 7, 0, 0, tzinfo=UTC)
_PACE_SEC_PER_KM = 300  # 5:00 min/km
_SPEED_MPS = 1000 / _PACE_SEC_PER_KM
_TOTAL_DISTANCE_M = 3000.0
_SEGMENT_GAP_S = 90
_ELEVATION_CLIMB_M = 20.0
# Kept small relative to the ~3.3 m/s (1s-sample) forward step: real GPS
# jitter is a small perturbation around the true path, not comparable in
# size to the distance actually covered between fixes. A larger jitter here
# would inflate naive point-to-point summed distance well past the fixture's
# known-answer tolerances, since AnalyzerV1 (deliberately, per the plan) does
# no path smoothing/simplification — only elevation gets that treatment.
_JITTER_METERS = 0.5
_EARTH_RADIUS_M = 6371000.0
_ORIGIN_LAT = 51.5
_ORIGIN_LON = -0.1

random.seed(20260101)  # deterministic fixture


def _offset_point(distance_m: float) -> tuple[float, float]:
    """A point distance_m due north of the origin, in a straight line — makes
    the expected haversine distance for any two points exactly known."""
    d_lat = (distance_m / _EARTH_RADIUS_M) * (180 / math.pi)
    return _ORIGIN_LAT + d_lat, _ORIGIN_LON


def _jitter_meters() -> tuple[float, float]:
    """A small random offset (lat_m, lon_m), each within +/-_JITTER_METERS."""
    return (
        random.uniform(-_JITTER_METERS, _JITTER_METERS),  # noqa: S311 -- deterministic fixture, not security-sensitive
        random.uniform(-_JITTER_METERS, _JITTER_METERS),  # noqa: S311 -- deterministic fixture, not security-sensitive
    )


def _meters_to_degrees(lat: float, dlat_m: float, dlon_m: float) -> tuple[float, float]:
    dlat = (dlat_m / _EARTH_RADIUS_M) * (180 / math.pi)
    dlon = (dlon_m / (_EARTH_RADIUS_M * math.cos(math.radians(lat)))) * (180 / math.pi)
    return dlat, dlon


def build_gpx() -> gpxpy.gpx.GPX:
    gpx = gpxpy.gpx.GPX()
    track = gpxpy.gpx.GPXTrack()
    gpx.tracks.append(track)

    total_seconds = int(_TOTAL_DISTANCE_M / _SPEED_MPS)
    midpoint_s = total_seconds // 2

    segment_a = gpxpy.gpx.GPXTrackSegment()
    segment_b = gpxpy.gpx.GPXTrackSegment()
    track.segments.append(segment_a)
    track.segments.append(segment_b)

    for t in range(total_seconds + 1):
        distance_m = _SPEED_MPS * t
        lat, lon = _offset_point(distance_m)
        jitter_lat_m, jitter_lon_m = _jitter_meters()
        dlat, dlon = _meters_to_degrees(lat, jitter_lat_m, jitter_lon_m)

        progress = distance_m / _TOTAL_DISTANCE_M
        elevation = progress * _ELEVATION_CLIMB_M

        if t <= midpoint_s:
            time = _START + timedelta(seconds=t)
            segment = segment_a
        else:
            # 90s gap inserted after the midpoint — the second segment's
            # wall-clock time jumps forward but pace/distance stay the same.
            time = _START + timedelta(seconds=t + _SEGMENT_GAP_S)
            segment = segment_b

        point = gpxpy.gpx.GPXTrackPoint(
            latitude=lat + dlat,
            longitude=lon + dlon,
            elevation=elevation,
            time=time,
        )
        segment.points.append(point)

    return gpx


def main() -> None:
    gpx = build_gpx()
    out_path = Path(__file__).parent / "sample_run.gpx"
    out_path.write_text(gpx.to_xml(), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
