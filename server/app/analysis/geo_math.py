import math

from app.analysis.track import Point

_EARTH_RADIUS_METERS = 6371000.0


def haversine_distance_meters(a: Point, b: Point) -> float:
    """Great-circle distance, in meters. Mirrors mobile/lib/domain/geo_math.dart
    (same formula, same Earth radius) so server and phone distances agree on
    identical input, even though the two never share code."""
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    d_lat = math.radians(b.lat - a.lat)
    d_lon = math.radians(b.lon - a.lon)

    h = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))
    return _EARTH_RADIUS_METERS * c


def speed_mps_between(a: Point, b: Point) -> float | None:
    dt_seconds = (b.time - a.time).total_seconds()
    if dt_seconds <= 0:
        return None
    return haversine_distance_meters(a, b) / dt_seconds
