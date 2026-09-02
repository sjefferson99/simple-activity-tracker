from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Point:
    lat: float
    lon: float
    ele: float | None
    time: datetime


@dataclass(frozen=True)
class Segment:
    points: list[Point]


@dataclass(frozen=True)
class Track:
    """A parsed GPX track — pure Dart-equivalent dataclasses, no gpxpy types
    leak past app/analysis/gpx_parser.py (same discipline as LocationSample
    vs geolocator in the mobile app)."""

    segments: list[Segment]

    @property
    def point_count(self) -> int:
        return sum(len(segment.points) for segment in self.segments)
