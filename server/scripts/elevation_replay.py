"""Elevation tuning replay — docs/BAROMETER-PLAN.md.

Replays every phone recording in a captures folder through each candidate
elevation algorithm and scores it against that recording's reference (a
barometric bike computer or watch, exported as FIT), so the algorithm for
issue #184's step 2 is chosen on evidence, and re-checked as recordings
are added. Run from server/ after adding a recording to the manifest:

    uv run python -m scripts.elevation_replay ../captures/elevation

The folder holds the phone GPX and reference FIT files plus manifest.json:

    [{"id": "2026-01-01-ride-0800", "phone": "....gpx", "reference": "....fit",
      "activity": "ride", "carry": "pocket", "notes": "..."}]

activity: run | walk | ride. carry: pocket | hand | armband | handlebar.
reference may be null (only loop closure is scored then). The folder is
gitignored: recordings hold home locations.

Scores, per recording with a reference, over the time both cover:
- shape: RMS of (candidate - reference) height once their offset is
  removed, in metres. How well the profile is followed.
- gain_err: |gain - ref gain| + |loss - ref loss| as a fraction of the
  reference's ref gain + loss. The reference's own totals are the device's
  judgement (FIT session), independent of any filter here.
Each candidate family's settings are also picked leave-one-out (tuned on
every other recording, scored on this one), which is the honest estimate
of how a setting does on a recording it wasn't tuned on.
"""

import argparse
import bisect
import itertools
import json
import math
import statistics
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import fitparse
import gpxpy

from app.analysis.elevation import ElevationAccumulator

_NS = "{https://simple-activity-tracker.local/gpx-extensions}"
# Metres of height per hPa near sea level; only used to put pressure spread
# on the same scale as heights.
_M_PER_HPA = 8.3
# GPS altitude accuracy assumed when the fix doesn't report one (recordings
# before the vertical_accuracy extension).
_DEFAULT_GPS_SD_M = 5.0
# Reference records further apart than this aren't interpolated across.
_MAX_REFERENCE_GAP_S = 10.0


@dataclass(frozen=True)
class Fix:
    t: float
    gps_m: float | None
    baro_m: float | None  # standard-atmosphere height relative to the first reading
    pressure_sd_hpa: float | None
    vertical_accuracy_m: float | None
    speed_mps: float
    motion_rms: float | None
    cadence_hz: float | None


@dataclass(frozen=True)
class Recording:
    id: str
    activity: str
    carry: str
    fixes: list[list[Fix]]  # per GPX segment (pause/resume)
    reference: list[tuple[float, float]] | None  # (t, height)
    reference_totals: tuple[float, float] | None  # session ascent, descent
    closes_loop: bool


Series = list[list[float | None]]  # height per fix, per segment
Candidate = Callable[[list[list[Fix]]], Series]


def _ext(point: Any, name: str) -> float | None:
    for element in point.extensions:
        if getattr(element, "tag", None) == _NS + name:
            try:
                value = float(element.text or "")
            except ValueError:
                return None
            return value if math.isfinite(value) else None
    return None


def _baro_height(pressure_hpa: float, p0: float) -> float:
    return 44330.0 * (1 - (pressure_hpa / p0) ** (1 / 5.255))


def load_phone(path: Path) -> tuple[list[list[Fix]], bool]:
    gpx = gpxpy.parse(path.read_text(encoding="utf-8"))
    segments: list[list[Fix]] = []
    p0: float | None = None
    first = last = None
    for track in gpx.tracks:
        for segment in track.segments:
            fixes = []
            for p in segment.points:
                if p.time is None:
                    continue
                accuracy = _ext(p, "accuracy")
                if accuracy is not None and accuracy > 25:  # same gate as the analysis
                    continue
                pressure = _ext(p, "pressure_hpa")
                if pressure is not None and pressure > 0 and p0 is None:
                    p0 = pressure
                fixes.append(
                    Fix(
                        t=p.time.timestamp(),
                        gps_m=p.elevation,
                        baro_m=_baro_height(pressure, p0) if pressure and p0 else None,
                        pressure_sd_hpa=_ext(p, "pressure_sd"),
                        vertical_accuracy_m=_ext(p, "vertical_accuracy"),
                        speed_mps=_ext(p, "speed") or 0.0,
                        motion_rms=_ext(p, "motion_rms"),
                        cadence_hz=_ext(p, "cadence_hz"),
                    )
                )
                first = first or p
                last = p
            if fixes:
                segments.append(fixes)
    closes_loop = first is not None and last is not None and (first.distance_2d(last) or 0) < 50
    return segments, closes_loop


def load_reference(path: Path) -> tuple[list[tuple[float, float]], tuple[float, float] | None]:
    records: list[tuple[float, float]] = []
    totals = None
    for message in fitparse.FitFile(str(path)).get_messages():
        values = message.get_values()
        if message.name == "record":
            height = values.get("enhanced_altitude", values.get("altitude"))
            if isinstance(values.get("timestamp"), datetime) and height is not None:
                records.append((values["timestamp"].timestamp(), float(height)))
        elif message.name == "session":
            ascent, descent = values.get("total_ascent"), values.get("total_descent")
            if ascent is not None and descent is not None:
                totals = (float(ascent), float(descent))
    return records, totals


def load(folder: Path) -> list[Recording]:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    recordings = []
    for entry in manifest:
        fixes, closes_loop = load_phone(folder / entry["phone"])
        reference = totals = None
        if entry.get("reference"):
            reference, totals = load_reference(folder / entry["reference"])
            # Only the time both devices cover is comparable.
            start, end = reference[0][0], reference[-1][0]
            fixes = [[f for f in seg if start <= f.t <= end] for seg in fixes]
            fixes = [seg for seg in fixes if seg]
        recordings.append(
            Recording(
                id=entry["id"],
                activity=entry["activity"],
                carry=entry["carry"],
                fixes=fixes,
                reference=reference,
                reference_totals=totals,
                closes_loop=closes_loop,
            )
        )
    return recordings


# --- Candidates -------------------------------------------------------------


def gps_181(segments: list[list[Fix]]) -> Series:
    """GPS altitude as the analysis uses it today (#181): the profile is the
    raw altitude, gain/loss come from ElevationAccumulator in _gain_loss."""
    return [[f.gps_m for f in seg] for seg in segments]


def baro_raw(segments: list[list[Fix]]) -> Series:
    return [[f.baro_m for f in seg] for seg in segments]


def wind_corrected(k: float) -> Candidate:
    """Barometer height minus k*v²: airflow over a pocket lowers pressure
    with the square of speed (measured ~1.7 m at 10 m/s on two rides)."""

    def run(segments: list[list[Fix]]) -> Series:
        return [
            [None if f.baro_m is None else f.baro_m - k * f.speed_mps**2 for f in seg]
            for seg in segments
        ]

    return run


def complementary(tau_level_s: float, wind_k: float = 0.0) -> Candidate:
    """Barometer for short-term change, GPS for the long-term level: the
    barometer plus a slowly tracked (barometer - GPS) offset. Falls back to
    GPS on fixes without pressure."""

    def run(segments: list[list[Fix]]) -> Series:
        out: Series = []
        for seg in segments:
            offset: float | None = None
            last_t: float | None = None
            heights: list[float | None] = []
            for f in seg:
                if f.baro_m is None:
                    heights.append(f.gps_m)
                    continue
                baro = f.baro_m - wind_k * f.speed_mps**2
                if f.gps_m is not None:
                    gap = baro - f.gps_m
                    if offset is None or last_t is None:
                        offset = gap
                    else:
                        alpha = 1 - math.exp(-(f.t - last_t) / tau_level_s)
                        offset += alpha * (gap - offset)
                    last_t = f.t
                heights.append(None if offset is None else baro - offset)
            out.append(heights)
        return out

    return run


def kalman(
    q_accel: float, q_bias: float, baro_floor_m: float, gps_scale: float, wind_k: float = 0.0
) -> Candidate:
    """Height, vertical speed and barometer offset, fed the barometer
    (weighted by its spread over the last second) and GPS (weighted by its
    reported vertical accuracy). Leans on whichever is quieter right now —
    a bouncing pocket on a run shifts weight to GPS, a calm ride to the
    barometer — instead of a rule per activity."""

    def run(segments: list[list[Fix]]) -> Series:
        out: Series = []
        for seg in segments:
            x: list[float] | None = None  # height, vertical speed, baro offset
            p = [[0.0] * 3 for _ in range(3)]
            last_t = 0.0
            heights: list[float | None] = []
            for f in seg:
                baro = None if f.baro_m is None else f.baro_m - wind_k * f.speed_mps**2
                if x is None:
                    if f.gps_m is None:
                        heights.append(None)
                        continue
                    x = [f.gps_m, 0.0, 0.0 if baro is None else baro - f.gps_m]
                    p = [[25.0, 0, 0], [0, 1.0, 0], [0, 0, 25.0]]
                    last_t = f.t
                    heights.append(x[0])
                    continue
                dt = max(f.t - last_t, 0.0)
                last_t = f.t
                # Predict (constant vertical speed, white-noise acceleration).
                x[0] += dt * x[1]
                p00 = p[0][0] + dt * (p[1][0] + p[0][1]) + dt * dt * p[1][1]
                p01, p11 = p[0][1] + dt * p[1][1], p[1][1]
                p[0][0] = p00 + q_accel * dt**3 / 3
                p[0][1] = p[1][0] = p01 + q_accel * dt**2 / 2
                p[1][1] = p11 + q_accel * dt
                p[0][2] = p[2][0] = p[0][2] + dt * p[1][2]
                p[2][2] += q_bias * dt
                if baro is not None:
                    sd = (f.pressure_sd_hpa or 0.0) * _M_PER_HPA
                    _update(x, p, [1.0, 0.0, 1.0], baro, max(sd, baro_floor_m) ** 2)
                if f.gps_m is not None:
                    gps_sd = (f.vertical_accuracy_m or _DEFAULT_GPS_SD_M) * gps_scale
                    _update(x, p, [1.0, 0.0, 0.0], f.gps_m, gps_sd**2)
                heights.append(x[0])
            out.append(heights)
        return out

    return run


def _update(x: list[float], p: list[list[float]], h: list[float], z: float, r: float) -> None:
    ph = [sum(p[i][j] * h[j] for j in range(3)) for i in range(3)]
    s = sum(h[i] * ph[i] for i in range(3)) + r
    k = [v / s for v in ph]
    innovation = z - sum(h[i] * x[i] for i in range(3))
    for i in range(3):
        x[i] += k[i] * innovation
    hp = [sum(h[i] * p[i][j] for i in range(3)) for j in range(3)]
    for i in range(3):
        for j in range(3):
            p[i][j] -= k[i] * hp[j]


# Gain/loss are counted from each candidate's heights with the #181
# accumulator's machinery: smoothing time constant, then a dead-band.
@dataclass(frozen=True)
class Counting:
    tau_s: float
    hysteresis_m: float


def _gain_loss(times: list[list[float]], series: Series, counting: Counting) -> tuple[float, float]:
    gain = loss = 0.0
    for seg_t, seg_h in zip(times, series, strict=True):
        smoothed: float | None = None
        reference: float | None = None
        last_t = 0.0
        for t, h in zip(seg_t, seg_h, strict=True):
            if h is None:
                continue
            if smoothed is None or reference is None:
                smoothed = reference = h
                last_t = t
                continue
            if counting.tau_s > 0 and t > last_t:
                smoothed += (1 - math.exp(-(t - last_t) / counting.tau_s)) * (h - smoothed)
            elif counting.tau_s == 0:
                smoothed = h
            last_t = t
            rise = smoothed - reference
            if rise >= counting.hysteresis_m:
                gain += rise
                reference = smoothed
            elif -rise >= counting.hysteresis_m:
                loss -= rise
                reference = smoothed
    return gain, loss


def _gps_181_gain_loss(segments: list[list[Fix]]) -> tuple[float, float]:
    accumulator = ElevationAccumulator()
    for seg in segments:
        accumulator.reset_anchor()
        for f in seg:
            accumulator.add(f.t, f.gps_m)
    return accumulator.gain_m, accumulator.loss_m


# --- Scoring ----------------------------------------------------------------


@dataclass(frozen=True)
class Score:
    shape_m: float | None
    gain_err: float | None
    gain_m: float
    loss_m: float
    loop_m: float | None  # end - start height on a recording that closes its loop


def _reference_at(
    reference: list[tuple[float, float]], times: list[float], t: float
) -> float | None:
    i = bisect.bisect_left(times, t)
    if i <= 0 or i >= len(times):
        return None
    (t0, h0), (t1, h1) = reference[i - 1], reference[i]
    if t1 - t0 > _MAX_REFERENCE_GAP_S:
        return None
    return h0 + (h1 - h0) * (t - t0) / (t1 - t0)


def score(recording: Recording, series: Series, gain_loss: tuple[float, float]) -> Score:
    gain, loss = gain_loss
    flat = [
        (f.t, h)
        for seg, hs in zip(recording.fixes, series, strict=True)
        for f, h in zip(seg, hs, strict=True)
        if h is not None
    ]
    shape = gain_err = loop = None
    if recording.reference and flat:
        ref_times = [t for t, _ in recording.reference]
        pairs = [(h, _reference_at(recording.reference, ref_times, t)) for t, h in flat]
        diffs = [h - r for h, r in pairs if r is not None]
        if len(diffs) > 10:
            offset = statistics.median(diffs)
            shape = math.sqrt(statistics.fmean((d - offset) ** 2 for d in diffs))
    if recording.reference_totals:
        ref_gain, ref_loss = recording.reference_totals
        if ref_gain + ref_loss > 0:
            gain_err = (abs(gain - ref_gain) + abs(loss - ref_loss)) / (ref_gain + ref_loss)
    if recording.closes_loop and not recording.reference and flat:
        loop = flat[-1][1] - flat[0][1]
    return Score(shape, gain_err, gain, loss, loop)


@dataclass(frozen=True)
class Setting:
    family: str
    label: str
    candidate: Candidate
    counting: Counting | None  # None: the #181 accumulator on GPS


def settings() -> list[Setting]:
    out = [Setting("gps_181", "GPS, #181 filter", gps_181, None)]
    countings = [Counting(tau, h) for tau, h in itertools.product((0, 5, 10), (0.5, 1, 2, 3))]
    for counting in countings:
        tag = f"tau{counting.tau_s:g} h{counting.hysteresis_m:g}"
        out.append(Setting("baro", f"baro {tag}", baro_raw, counting))
        out.append(Setting("baro_wind", f"baro wind {tag}", wind_corrected(0.017), counting))
    for tau_level, counting in itertools.product(
        (120, 300, 900), [Counting(tau, h) for tau, h in itertools.product((0, 5), (1, 2))]
    ):
        tag = f"level{tau_level} tau{counting.tau_s:g} h{counting.hysteresis_m:g}"
        out.append(Setting("blend", f"blend {tag}", complementary(tau_level), counting))
    for q_a, q_b, floor, gps_scale, hyst in itertools.product(
        (0.01, 0.05, 0.2), (1e-4, 1e-3), (0.2, 0.5), (1, 3), (0.5, 1, 2)
    ):
        tag = f"qa{q_a:g} qb{q_b:g} floor{floor:g} gpsx{gps_scale:g} h{hyst:g}"
        out.append(
            Setting(
                "kalman", f"kalman {tag}", kalman(q_a, q_b, floor, gps_scale), Counting(0, hyst)
            )
        )
    return out


def _metric(s: Score) -> float | None:
    """What a setting is picked by: gain/loss error, the figure users see;
    shape where a reference has no session totals."""
    if s.gain_err is not None:
        return s.gain_err
    return None if s.shape_m is None else s.shape_m / 10


def evaluate(recordings: list[Recording]) -> dict[str, Any]:
    all_settings = settings()
    has_baro = {r.id: any(f.baro_m is not None for seg in r.fixes for f in seg) for r in recordings}
    results: dict[str, dict[str, Score]] = {}
    for setting in all_settings:
        results[setting.label] = {}
        for r in recordings:
            if setting.family != "gps_181" and not has_baro[r.id]:
                continue
            series = setting.candidate(r.fixes)
            times = [[f.t for f in seg] for seg in r.fixes]
            gain_loss = (
                _gps_181_gain_loss(r.fixes)
                if setting.counting is None
                else _gain_loss(times, series, setting.counting)
            )
            results[setting.label][r.id] = score(r, series, gain_loss)
    return {"settings": all_settings, "results": results}


def _mean(values: Iterable[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return statistics.fmean(present) if present else None


def report(recordings: list[Recording], evaluation: dict[str, Any]) -> dict[str, Any]:
    all_settings: list[Setting] = evaluation["settings"]
    results: dict[str, dict[str, Score]] = evaluation["results"]
    scored = [r for r in recordings if r.reference]
    lines = ["Recordings:"]
    for r in recordings:
        n = sum(len(seg) for seg in r.fixes)
        baro = any(f.baro_m is not None for seg in r.fixes for f in seg)
        motion = [f.motion_rms for seg in r.fixes for f in seg if f.motion_rms is not None]
        cadence = [f.cadence_hz for seg in r.fixes for f in seg if f.cadence_hz is not None]
        extras = ""
        if motion:
            extras = f", motion {statistics.median(motion):.1f} m/s²"
        if cadence:
            extras += f", cadence {statistics.median(cadence):.2f} Hz ({len(cadence) / n:.0%})"
        totals = r.reference_totals
        ref = f"{totals[0]:g}/{totals[1]:g} m" if totals else None
        lines.append(
            f"  {r.id}: {r.activity}/{r.carry}, {n} fixes, barometer {'yes' if baro else 'no'}, "
            f"reference {ref or ('profile' if r.reference else 'none')}"
            f"{extras}"
        )

    summary: dict[str, Any] = {"families": {}}
    lines.append("\nBest setting per family (mean over recordings with a reference):")
    for family in dict.fromkeys(s.family for s in all_settings):
        members = [s for s in all_settings if s.family == family]

        def mean_metric(s: Setting, exclude: str | None = None) -> float | None:
            return _mean(
                _metric(results[s.label][r.id])
                for r in scored
                if r.id != exclude and r.id in results[s.label]
            )

        ranked = sorted(
            (m for m in members if mean_metric(m) is not None),
            key=lambda m: mean_metric(m) or math.inf,
        )
        if not ranked:
            continue
        best = ranked[0]
        # Leave-one-out: pick on the others, score on this one.
        loo = []
        for r in scored:
            pool = [m for m in members if mean_metric(m, exclude=r.id) is not None]
            if not pool or r.id not in results[best.label]:
                continue
            pick = min(pool, key=lambda m: mean_metric(m, exclude=r.id) or math.inf)
            loo.append(_metric(results[pick.label][r.id]))
        shape = _mean(
            results[best.label][r.id].shape_m for r in scored if r.id in results[best.label]
        )
        loo_mean = _mean(loo)
        summary["families"][family] = {
            "best": best.label,
            "gain_err": mean_metric(best),
            "loo_gain_err": loo_mean,
            "shape_m": shape,
        }
        lines.append(
            f"  {family:9} {best.label:48} gain err {mean_metric(best):5.1%}"
            f"  leave-one-out {'—' if loo_mean is None else f'{loo_mean:5.1%}'}"
            f"  shape {'—' if shape is None else f'{shape:4.2f} m'}"
        )
        for r in recordings:
            s = results[best.label].get(r.id)
            if s is None:
                continue
            ref = r.reference_totals
            parts = [f"{s.gain_m:5.1f}/{s.loss_m:5.1f} m"]
            if ref:
                parts.append(f"ref {ref[0]:g}/{ref[1]:g}")
            if s.shape_m is not None:
                parts.append(f"shape {s.shape_m:.2f} m")
            if s.loop_m is not None:
                parts.append(f"loop closes to {s.loop_m:+.1f} m")
            lines.append(f"      {r.id:28} " + ", ".join(parts))
    print("\n".join(lines))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--save", action="store_true", help="write results-<date>.json alongside")
    args = parser.parse_args(argv)
    recordings = load(args.folder)
    summary = report(recordings, evaluate(recordings))
    if args.save:
        out = args.folder / f"results-{datetime.now():%Y-%m-%d}.json"
        out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"\nSaved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
