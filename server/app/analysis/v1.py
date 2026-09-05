import itertools
from dataclasses import dataclass, field

from app.analysis.analyzer import AnalysisResult
from app.analysis.geo_math import haversine_distance_meters, speed_mps_between
from app.analysis.track import Point, Track

ANALYSIS_VERSION = 2

_MAX_IMPLIED_SPEED_MPS = 12.5  # ~2:08 min/km; faster than that is treated as a GPS jump
_MOVING_SPEED_THRESHOLD_MPS = 0.5
_SPLIT_METERS = 1000.0
_SERIES_MAX_SAMPLES = 300
_BEST_EFFORT_DISTANCES_METERS = (1000.0, 5000.0, 10000.0)

# Matches mobile MetricsEngine's _currentSpeedWindow: a per-step instant
# speed (distance / dt between two consecutive fixes ~0.5-1.5s apart) is
# dominated by GPS position jitter at that timescale, since the noise is
# comparable in size to the actual distance covered per step. A time-based
# displacement window smooths that out — and unlike summing per-step
# distances, straight-line displacement over the window also cancels out
# small back-and-forth wobble instead of accumulating it.
_SPEED_WINDOW_SECONDS = 3.0


@dataclass
class _Step:
    """One accepted point-to-point step, with its running totals."""

    point: Point
    distance_m: float  # this step's own distance
    dt_s: float
    speed_mps: float | None
    cum_distance_m: float  # cumulative distance including this step
    cum_time_s: float  # cumulative wall-clock elapsed including this step


@dataclass
class _SplitBuilder:
    index: int
    start_distance_m: float
    start_time_s: float
    start_ele: float | None
    elevation_delta_m: float = 0.0


def _smoothed_elevations(points: list[Point]) -> list[float | None]:
    """3-point centered moving average on ele, edges left as-is — raw GPS
    elevation is noisy and inflates gain/loss badly if summed directly."""
    n = len(points)
    result: list[float | None] = [p.ele for p in points]
    for i in range(1, n - 1):
        a, b, c = points[i - 1].ele, points[i].ele, points[i + 1].ele
        if a is not None and b is not None and c is not None:
            result[i] = (a + b + c) / 3
    return result


def _build_steps(track: Track) -> list[_Step]:
    steps: list[_Step] = []
    cum_distance = 0.0
    cum_time = 0.0
    for segment in track.segments:
        for prev, curr in zip(segment.points, segment.points[1:], strict=False):
            distance = haversine_distance_meters(prev, curr)
            speed = speed_mps_between(prev, curr)
            dt = (curr.time - prev.time).total_seconds()
            if speed is not None and speed > _MAX_IMPLIED_SPEED_MPS:
                # v1 behaviour: drop the step entirely rather than try to
                # re-anchor (unlike the phone's live filter, which needs to
                # keep tracking through a jump) — a finished GPX is analysed
                # once, so simply excluding the bad step is enough.
                continue
            cum_distance += distance
            cum_time += max(dt, 0.0)
            steps.append(
                _Step(
                    point=curr,
                    distance_m=distance,
                    dt_s=dt,
                    speed_mps=speed,
                    cum_distance_m=cum_distance,
                    cum_time_s=cum_time,
                )
            )
    return steps


def _compute_splits(steps: list[_Step], first_point: Point) -> list[dict[str, object]]:
    if not steps:
        return []

    splits: list[dict[str, object]] = []
    builder = _SplitBuilder(
        index=1, start_distance_m=0.0, start_time_s=0.0, start_ele=first_point.ele
    )
    prev_cum_time = 0.0
    prev_ele = first_point.ele

    for step in steps:
        builder.elevation_delta_m += _elevation_delta(prev_ele, step.point.ele)
        prev_ele = step.point.ele

        next_boundary = builder.index * _SPLIT_METERS
        if step.cum_distance_m >= next_boundary and step.distance_m > 0:
            # Interpolate the crossing time — a point rarely lands exactly
            # on the 1km boundary (mirrors mobile MetricsEngine's approach).
            overshoot = step.cum_distance_m - next_boundary
            fraction = 1 - (overshoot / step.distance_m)
            crossing_time_s = prev_cum_time + fraction * step.dt_s
            duration_s = crossing_time_s - builder.start_time_s
            split_distance_m = next_boundary - builder.start_distance_m
            avg_speed = split_distance_m / duration_s if duration_s > 0 else 0.0
            splits.append(
                {
                    "index": builder.index,
                    "duration_seconds": duration_s,
                    "avg_speed_mps": avg_speed,
                    "elevation_delta_m": builder.elevation_delta_m,
                }
            )
            builder = _SplitBuilder(
                index=builder.index + 1,
                start_distance_m=next_boundary,
                start_time_s=crossing_time_s,
                start_ele=step.point.ele,
            )

        prev_cum_time = step.cum_time_s

    return splits


def _elevation_delta(prev_ele: float | None, curr_ele: float | None) -> float:
    if prev_ele is None or curr_ele is None:
        return 0.0
    return curr_ele - prev_ele


def _elevation_stats(smoothed: list[float | None]) -> dict[str, float | None]:
    values = [e for e in smoothed if e is not None]
    if not values:
        return {"gain_m": None, "loss_m": None, "min_m": None, "max_m": None}

    gain = 0.0
    loss = 0.0
    for prev, curr in itertools.pairwise(values):
        delta = curr - prev
        if delta > 0:
            gain += delta
        else:
            loss += -delta
    return {"gain_m": gain, "loss_m": loss, "min_m": min(values), "max_m": max(values)}


def _best_efforts(steps: list[_Step]) -> list[dict[str, object]]:
    """Fastest window for each target distance, via a two-pointer sweep over
    cumulative distance/time (steps are monotonically increasing in both)."""
    if not steps:
        return []

    total_distance = steps[-1].cum_distance_m
    results: list[dict[str, object]] = []

    for target in _BEST_EFFORT_DISTANCES_METERS:
        if target > total_distance:
            continue

        best_duration: float | None = None
        start = 0
        # cum_distance_m/cum_time_s *before* step i is the previous step's
        # cumulative total, or 0 for the first step.
        prev_cum_distance = [0.0] + [s.cum_distance_m for s in steps[:-1]]
        prev_cum_time = [0.0] + [s.cum_time_s for s in steps[:-1]]

        for end in range(len(steps)):
            while (
                start < end and steps[end].cum_distance_m - prev_cum_distance[start + 1] >= target
            ):
                start += 1
            window_distance = steps[end].cum_distance_m - prev_cum_distance[start]
            if window_distance < target:
                continue
            window_time = steps[end].cum_time_s - prev_cum_time[start]
            if window_time <= 0:
                continue
            if best_duration is None or window_time < best_duration:
                best_duration = window_time

        if best_duration is not None:
            results.append(
                {
                    "distance_meters": target,
                    "duration_seconds": best_duration,
                    "avg_speed_mps": target / best_duration,
                }
            )

    return results


def _windowed_speeds(steps: list[_Step], first_point: Point) -> list[float | None]:
    """Speed at each step, smoothed the same way mobile MetricsEngine smooths
    its live current-speed reading (see _SPEED_WINDOW_SECONDS): displacement
    over the last ~3s of steps, not the single-step instant speed. Returns
    one value per step (same length/order as `steps`), None where fewer than
    2 points fall in the window (only possible for the very first step)."""
    if not steps:
        return []

    result: list[float | None] = []
    start = 0  # index into steps of the oldest step still inside the window
    for end in range(len(steps)):
        while (
            start < end and steps[end].cum_time_s - steps[start].cum_time_s > _SPEED_WINDOW_SECONDS
        ):
            start += 1
        window_start_point = first_point if start == 0 else steps[start - 1].point
        result.append(speed_mps_between(window_start_point, steps[end].point))
    return result


def _series(
    steps: list[_Step],
    smoothed: list[float | None],
    windowed_speeds: list[float | None],
    first_point: Point,
) -> list[dict[str, object]]:
    """t_s is accumulated moving time (cum_time_s), not wall-clock elapsed —
    it never advances across a gap between segments (a pause, or a stretch
    with no GPS fixes), the same way moving_seconds and the splits don't
    credit that gap either. A wall-clock x-axis would show a flat, dataless
    stretch across every pause; a moving-time axis keeps the pace/elevation
    chart continuous, matching what the runner actually experienced."""
    if not steps:
        return []

    n = len(steps)
    # Reserve room for the leading t=0 anchor and a possible trailing
    # closing sample, so the total never exceeds _SERIES_MAX_SAMPLES.
    budget = max(1, _SERIES_MAX_SAMPLES - 2)
    stride = max(1, -(-n // budget))  # ceil division
    samples: list[dict[str, object]] = [
        {
            "t_s": 0.0,
            "dist_m": 0.0,
            "speed_mps": None,
            "ele_m": first_point.ele,
        }
    ]
    for i in range(0, n, stride):
        step = steps[i]
        samples.append(
            {
                "t_s": step.cum_time_s,
                "dist_m": step.cum_distance_m,
                "speed_mps": windowed_speeds[i],
                "ele_m": smoothed[i + 1] if i + 1 < len(smoothed) else step.point.ele,
            }
        )
    if samples[-1]["t_s"] != steps[-1].cum_time_s:
        last_index = len(steps) - 1
        last = steps[last_index]
        samples.append(
            {
                "t_s": last.cum_time_s,
                "dist_m": last.cum_distance_m,
                "speed_mps": windowed_speeds[last_index],
                "ele_m": smoothed[-1] if smoothed else last.point.ele,
            }
        )
    return samples


def _bounds(track: Track) -> dict[str, float] | None:
    lats = [p.lat for segment in track.segments for p in segment.points]
    lons = [p.lon for segment in track.segments for p in segment.points]
    if not lats:
        return None
    return {
        "min_lat": min(lats),
        "max_lat": max(lats),
        "min_lon": min(lons),
        "max_lon": max(lons),
    }


@dataclass
class AnalyzerV1:
    version: int = field(default=ANALYSIS_VERSION, init=False)

    def analyze(self, track: Track) -> AnalysisResult:
        all_points = [p for segment in track.segments for p in segment.points]
        if not all_points:
            raise ValueError("Track has no points")

        steps = _build_steps(track)
        smoothed = _smoothed_elevations(all_points)
        windowed_speeds = _windowed_speeds(steps, all_points[0])

        total_distance_m = steps[-1].cum_distance_m if steps else 0.0
        elapsed_s = (all_points[-1].time - all_points[0].time).total_seconds()
        moving_s = sum(
            s.dt_s
            for s in steps
            if s.speed_mps is not None and s.speed_mps >= _MOVING_SPEED_THRESHOLD_MPS
        )
        avg_moving_speed_mps = total_distance_m / moving_s if moving_s > 0 else None

        return {
            "analysis_version": ANALYSIS_VERSION,
            "distance_meters": total_distance_m,
            "elapsed_seconds": elapsed_s,
            "moving_seconds": moving_s,
            "avg_moving_speed_mps": avg_moving_speed_mps,
            "elevation": _elevation_stats(smoothed),
            "splits": _compute_splits(steps, all_points[0]),
            "best_efforts": _best_efforts(steps),
            "series": _series(steps, smoothed, windowed_speeds, all_points[0]),
            "bounds": _bounds(track),
            "point_count": track.point_count,
            "segment_count": len(track.segments),
        }
