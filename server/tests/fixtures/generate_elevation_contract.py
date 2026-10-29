"""Generates contract/elevation/gps-noise.json — the shared replay both the
server (tests/test_elevation.py) and the app
(mobile/test/domain/tracking/elevation_accumulator_test.dart) must turn into
the same gain/loss. Run from server/ after a deliberate algorithm change:

    uv run python -m tests.fixtures.generate_elevation_contract

Synthetic but shaped like real phone GPS altitude: a 40 m hill with ~1.5 m
per-fix jitter plus slow wander, 1 Hz with irregular gaps, a pause (second
segment), fixes with no altitude and a few wild altitude spikes.
"""

import json
import math
import random
from pathlib import Path

from app.analysis.elevation import (
    ELEVATION_HYSTERESIS_M,
    ELEVATION_MAX_VERTICAL_SPEED_MPS,
    ELEVATION_SMOOTHING_TAU_S,
    ElevationAccumulator,
)

_OUT = Path(__file__).resolve().parents[3] / "contract" / "elevation" / "gps-noise.json"


def _segments() -> list[list[tuple[float, float | None]]]:
    rng = random.Random(181)  # noqa: S311 -- deterministic fixture, not security-sensitive
    segments: list[list[tuple[float, float | None]]] = []
    t = 0.0
    wander = 0.0
    for seg_index, duration_s in enumerate((900, 600)):
        points: list[tuple[float, float | None]] = []
        end = t + duration_s
        while t < end:
            wander = 0.98 * wander + rng.gauss(0, 0.3)
            progress = (t % 900) / 900
            hill = 40 * math.sin(math.pi * progress) if seg_index == 0 else 5 * progress
            ele: float | None = round(50 + hill + wander + rng.gauss(0, 1.5), 2)
            if rng.random() < 0.02:
                ele = None
            elif rng.random() < 0.005:
                ele = 500.0  # a wild fix the vertical-rate limit must absorb
            points.append((round(t, 3), ele))
            t += 1.0 if rng.random() < 0.9 else rng.choice((0.0, 2.0, 5.0))
        segments.append(points)
        t += 120  # paused
    return segments


def main() -> None:
    segments = _segments()
    accumulator = ElevationAccumulator()
    for points in segments:
        accumulator.reset_anchor()
        for t_s, ele in points:
            accumulator.add(t_s, ele)
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(
        json.dumps(
            {
                "_about": "Shared elevation-gain replay (issue #181): app and server must "
                "produce expected from segments. See contract/README.md.",
                "tau_s": ELEVATION_SMOOTHING_TAU_S,
                "hysteresis_m": ELEVATION_HYSTERESIS_M,
                "max_vertical_speed_mps": ELEVATION_MAX_VERTICAL_SPEED_MPS,
                "expected": {"gain_m": accumulator.gain_m, "loss_m": accumulator.loss_m},
                "segments": [[[t_s, ele] for t_s, ele in points] for points in segments],
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
