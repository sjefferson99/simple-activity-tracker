"""Elevation gain/loss from phone GPS altitude — issue #181."""

import json
import math
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.analysis.elevation import (
    ELEVATION_HYSTERESIS_M,
    ELEVATION_MAX_VERTICAL_SPEED_MPS,
    ELEVATION_SMOOTHING_TAU_S,
    ElevationAccumulator,
    is_phone_gps_track,
)
from app.analysis.track import Point, Segment, Track
from app.analysis.v1 import AnalyzerV1

_CONTRACT = Path(__file__).resolve().parents[2] / "contract" / "elevation" / "gps-noise.json"
_START = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)


def _track(eles: list[float | None], creator: str | None = "Simple Activity Tracker") -> Track:
    """1 Hz fixes heading north at ~1.4 m/s (a walk) with the given altitudes."""
    points = [
        Point(
            lat=50.9 + i * 0.0000126,
            lon=-1.34,
            ele=ele,
            time=_START + timedelta(seconds=i),
            accuracy_m=4.0,
            speed_mps=1.4,
        )
        for i, ele in enumerate(eles)
    ]
    return Track(segments=[Segment(points=points)], creator=creator)


def test_contract_replay_matches_the_app() -> None:
    """The app replays the same file (elevation_accumulator_test.dart) and must
    land on the same totals — this is what keeps the live tile and the
    analysis in agreement."""
    contract = json.loads(_CONTRACT.read_text(encoding="utf-8"))
    assert contract["tau_s"] == ELEVATION_SMOOTHING_TAU_S
    assert contract["hysteresis_m"] == ELEVATION_HYSTERESIS_M
    assert contract["max_vertical_speed_mps"] == ELEVATION_MAX_VERTICAL_SPEED_MPS

    accumulator = ElevationAccumulator()
    for points in contract["segments"]:
        accumulator.reset_anchor()
        for t_s, ele in points:
            accumulator.add(t_s, ele)

    assert accumulator.gain_m == pytest.approx(contract["expected"]["gain_m"], abs=1e-6)
    assert accumulator.loss_m == pytest.approx(contract["expected"]["loss_m"], abs=1e-6)


def test_noisy_flat_track_has_almost_no_gain() -> None:
    rng = random.Random(5)  # noqa: S311 -- deterministic fixture, not security-sensitive
    eles: list[float | None] = [40 + rng.gauss(0, 1.5) for _ in range(3600)]
    elevation = AnalyzerV1().analyze(_track(eles))["elevation"]
    assert elevation["gain_m"] < 6
    assert elevation["loss_m"] < 6


def test_a_real_climb_is_counted_in_full() -> None:
    rng = random.Random(7)  # noqa: S311 -- deterministic fixture, not security-sensitive
    eles: list[float | None] = [
        50 + 60 * math.sin(math.pi * i / 1200) + rng.gauss(0, 1.5) for i in range(1201)
    ]
    elevation = AnalyzerV1().analyze(_track(eles))["elevation"]
    assert elevation["gain_m"] == pytest.approx(60, abs=6)
    assert elevation["loss_m"] == pytest.approx(60, abs=6)
    assert elevation["max_m"] == pytest.approx(110, abs=3)


def test_a_single_wild_altitude_is_not_a_climb() -> None:
    eles: list[float | None] = [40.0] * 600
    eles[300] = 5000.0
    elevation = AnalyzerV1().analyze(_track(eles))["elevation"]
    assert elevation["gain_m"] == 0
    assert elevation["max_m"] == pytest.approx(40, abs=1)


def test_climb_while_paused_is_not_counted() -> None:
    accumulator = ElevationAccumulator()
    accumulator.add(0, 100.0)
    accumulator.add(1, 100.0)
    accumulator.reset_anchor()
    accumulator.add(600, 150.0)
    accumulator.add(601, 150.0)
    assert accumulator.gain_m == 0


def test_fixes_without_altitude_are_skipped() -> None:
    accumulator = ElevationAccumulator()
    for t in range(200):
        accumulator.add(t, None if t % 2 else 100.0 + t * 0.1)
    # 19.8 m climbed; the dead-band holds back up to its own width at the end.
    assert 19.8 - ELEVATION_HYSTERESIS_M - 1 < accumulator.gain_m <= 19.8
    assert accumulator.loss_m == 0


def test_imported_tracks_keep_their_recorded_elevation_smoothing() -> None:
    """A Strava/Garmin import is often barometric or already smoothed — the
    GPS filter would wrongly flatten its small real undulations."""
    eles: list[float | None] = [50 + (2 if (i // 20) % 2 else 0) for i in range(400)]
    imported = AnalyzerV1().analyze(_track(eles, creator="simple-activity-tracker"))
    phone = AnalyzerV1().analyze(_track(eles))
    assert imported["elevation"]["gain_m"] == pytest.approx(10 * 2, abs=1)
    assert phone["elevation"]["gain_m"] == 0


@pytest.mark.parametrize(
    ("creator", "expected"),
    [
        ("Simple Activity Tracker", True),
        ("Simple Activity Tracker (live)", True),
        ("Simple Runner", True),
        ("simple-activity-tracker", False),
        ("StravaGPX", False),
        (None, False),
    ],
)
def test_phone_gps_tracks_are_recognised_by_creator(creator: str | None, expected: bool) -> None:
    assert is_phone_gps_track(creator) is expected
