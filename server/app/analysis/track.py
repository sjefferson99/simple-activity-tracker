from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Point:
    lat: float
    lon: float
    ele: float | None
    time: datetime
    # From the optional sat:accuracy/sat:has_accuracy GPX extensions (mobile
    # only, see gpx_parser.parse_gpx) — None when absent/unmeasured, distinct
    # from a genuinely good accuracy value.
    accuracy_m: float | None = None
    # From the optional sat:speed/sat:has_speed GPX extensions (mobile only,
    # see gpx_parser.parse_gpx) — the GNSS chip's own Doppler-derived speed
    # for this fix, None when absent/unmeasured. Same "missing is not the
    # same as a measured zero" treatment as accuracy_m: a platform can report
    # a bare 0.0 for "no speed available" rather than omitting the field, so
    # has_speed is what actually distinguishes the two (see mobile's
    # LocationSample.hasSpeed doc for why).
    speed_mps: float | None = None


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


# A point whose sat:accuracy extension reports worse than this is dropped by
# drop_inaccurate_points() — same 25m threshold and "missing accuracy is not
# the same as good accuracy" treatment as mobile MetricsEngine's own live
# filter (_maxAcceptableAccuracyMeters). A GPX with no accuracy data at all
# (an old recording, a non-mobile import) is unaffected: Point.accuracy_m is
# None, which never triggers this filter.
MAX_ACCEPTABLE_ACCURACY_M = 25.0


def drop_inaccurate_points(points: list[Point]) -> list[Point]:
    """Excludes points whose sat:accuracy extension reports worse than
    MAX_ACCEPTABLE_ACCURACY_M — chiefly the stale/cold fix mobile devices
    sometimes report before GPS has a real lock (issue #83: such a point
    could become an analysis' `start`, skew its `bounds`, and appear as a
    stray marker on the map, even though the implied-speed jump check already
    excludes the *step* into/out of it). Shared by AnalyzerV1 and
    track_sampling.sample_track so the map and the analysis agree on which
    points are trustworthy. A point with no accuracy data at all
    (accuracy_m is None) is always kept."""
    return [p for p in points if p.accuracy_m is None or p.accuracy_m <= MAX_ACCEPTABLE_ACCURACY_M]
