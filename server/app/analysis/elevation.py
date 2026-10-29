"""Elevation gain/loss from phone GPS altitude (issue #181).

GPS altitude jitters by a few metres from fix to fix, and summing every wobble
as climb overstated a 3.5 h walk's ascent ~2.5x (858 m vs ~330 m on Strava).
Three stages fix that:

1. A time-based exponential moving average (time constant
   ELEVATION_SMOOTHING_TAU_S), so the smoothing is the same whatever the fix
   rate, rather than a fixed number of points.
2. A vertical-rate limit: each fix may pull the average at most
   ELEVATION_MAX_VERTICAL_SPEED_MPS per second towards itself, so a single
   wild altitude (a bad fix the distance filters may also reject — but only
   the GPS filters, which differ slightly between app and server) can't
   register as a climb. No one on foot or a bike climbs or drops that fast.
3. A dead-band: climb or descent is only counted once the smoothed altitude
   has moved ELEVATION_HYSTERESIS_M away from the last counted level.

ElevationAccumulator is causal (it only ever looks at fixes it has already
seen), so the phone can run the very same algorithm live. Its Dart twin is
mobile/lib/domain/tracking/elevation_accumulator.dart: same constants, same
steps. Both test suites replay contract/elevation/ and must agree, so the
live "Elevation gain" tile matches the analysis afterwards.

Tuned by replaying all 34 phone recordings on the dev server against an SRTM
terrain lookup, and the #181 walk against Strava: tau 10 s / 3 m gives 337 m
for that walk, and agrees with the terrain model to within a few metres on
the regular runs and rides.
"""

import math
from dataclasses import replace
from datetime import datetime

from app.analysis.track import Point

ELEVATION_SMOOTHING_TAU_S = 10.0
ELEVATION_HYSTERESIS_M = 3.0
ELEVATION_MAX_VERTICAL_SPEED_MPS = 5.0

# The creators our own mobile app writes (RunGpxLog, the server's live-session
# conversion, and the pre-rename app). Their <ele> is raw phone GPS altitude
# and gets the filter above. Anything else (Strava/Garmin imports, other
# trackers) is often barometric or already smoothed by its source, and the
# filter would wrongly flatten it, so it keeps the older light smoothing.
_PHONE_GPS_CREATORS = ("Simple Activity Tracker", "Simple Runner")


def is_phone_gps_track(creator: str | None) -> bool:
    return creator is not None and creator.startswith(_PHONE_GPS_CREATORS)


class ElevationAccumulator:
    """Feed fixes in time order with add(); call reset_anchor() at every
    pause/resume (a GPX <trkseg> boundary) so a height change while paused
    isn't counted. Fixes with no altitude are skipped."""

    def __init__(self) -> None:
        self.gain_m = 0.0
        self.loss_m = 0.0
        self._smoothed: float | None = None
        self._reference: float | None = None
        self._last_t_s: float | None = None

    def add(self, t_s: float, ele_m: float | None) -> None:
        if ele_m is None:
            return
        if self._smoothed is None or self._reference is None or self._last_t_s is None:
            self._smoothed = ele_m
            self._reference = ele_m
            self._last_t_s = t_s
            return
        dt_s = t_s - self._last_t_s
        if dt_s > 0:
            limit = ELEVATION_MAX_VERTICAL_SPEED_MPS * dt_s
            target = min(max(ele_m, self._smoothed - limit), self._smoothed + limit)
            alpha = 1 - math.exp(-dt_s / ELEVATION_SMOOTHING_TAU_S)
            self._smoothed += alpha * (target - self._smoothed)
            self._last_t_s = t_s
        rise = self._smoothed - self._reference
        if rise >= ELEVATION_HYSTERESIS_M:
            self.gain_m += rise
            self._reference = self._smoothed
        elif -rise >= ELEVATION_HYSTERESIS_M:
            self.loss_m += -rise
            self._reference = self._smoothed

    def reset_anchor(self) -> None:
        self._smoothed = None
        self._reference = None
        self._last_t_s = None


def gain_and_loss(segments: list[list[Point]]) -> tuple[float, float]:
    accumulator = ElevationAccumulator()
    for points in segments:
        accumulator.reset_anchor()
        for p in points:
            accumulator.add(p.time.timestamp(), p.ele)
    return accumulator.gain_m, accumulator.loss_m


def smooth_profile(points: list[Point]) -> list[Point]:
    """One segment's points with ele replaced by a zero-lag smoothed profile:
    the same time-based EMA run forwards then backwards, so the chart, min/max
    and per-split deltas aren't shifted ~10 s late the way the live (causal)
    filter is. Only the gain/loss totals need to match the phone exactly."""
    forward = _ema([(p.time, p.ele) for p in points])
    backward = _ema(list(zip([p.time for p in points], forward, strict=True))[::-1])[::-1]
    return [replace(p, ele=ele) for p, ele in zip(points, backward, strict=True)]


def _ema(samples: list[tuple[datetime, float | None]]) -> list[float | None]:
    out: list[float | None] = []
    smoothed: float | None = None
    last_time: datetime | None = None
    for time, ele in samples:
        if ele is None:
            out.append(None)
            continue
        if smoothed is None or last_time is None:
            smoothed = ele
        else:
            dt_s = abs((time - last_time).total_seconds())
            limit = ELEVATION_MAX_VERTICAL_SPEED_MPS * dt_s
            target = min(max(ele, smoothed - limit), smoothed + limit)
            smoothed += (1 - math.exp(-dt_s / ELEVATION_SMOOTHING_TAU_S)) * (target - smoothed)
        last_time = time
        out.append(smoothed)
    return out
