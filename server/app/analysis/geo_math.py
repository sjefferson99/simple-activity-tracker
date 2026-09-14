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


# Meters per degree of latitude (and, at the equator, of longitude) — the
# mean value along a meridian, accurate enough for the tolerance a "within N
# km of this point" search needs (issue #76).
_METERS_PER_DEGREE = 111_320.0


def equirectangular_scale(lat_deg: float) -> tuple[float, float]:
    """Returns (k_lat, k_lon): meters per degree of latitude and, at this
    latitude, meters per degree of longitude — for a cheap equirectangular
    approximation of distance from a fixed point, usable directly in SQL as
    plain arithmetic (see ActivityListFilters' location filter in
    app/repositories/activities.py):

        ((lat_col - lat) * k_lat) ** 2 + ((lon_col - lon) * k_lon) ** 2 <= radius_m ** 2

    This is an approximation, not the haversine great-circle distance used
    elsewhere in this module — it assumes a locally flat Earth around
    (lat_deg, lon), which is why k_lon depends on latitude (a degree of
    longitude shrinks towards the poles) while k_lat doesn't. The error is
    well under 0.5% for radii up to ~50km at any latitude a runner is
    realistically at, comfortably inside GPS noise, and it degrades badly
    only near the poles or across the antimeridian — neither is a concern
    here. It is *not* accurate enough to reuse for the analyzer's own
    distance/speed calculations, which keep using haversine_distance_meters
    for exactly that reason.
    """
    k_lat = _METERS_PER_DEGREE
    k_lon = _METERS_PER_DEGREE * math.cos(math.radians(lat_deg))
    return k_lat, k_lon
