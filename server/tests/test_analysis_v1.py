from pathlib import Path

import pytest

from app.analysis.gpx_parser import parse_gpx
from app.analysis.v1 import AnalyzerV1

_FIXTURE = Path(__file__).parent / "fixtures" / "sample_run.gpx"

# Fixture parameters (see tests/fixtures/generate_sample_run.py):
# 3km at a constant 5:00 min/km pace, split into two segments with a 90s
# gap, +20m elevation climb spread evenly over the distance.
_EXPECTED_DISTANCE_M = 3000.0
_EXPECTED_MOVING_S = 900.0  # 3km at 5:00/km
_EXPECTED_ELAPSED_S = 900.0 + 90.0  # moving time + the inserted gap
_EXPECTED_AVG_SPEED_MPS = _EXPECTED_DISTANCE_M / _EXPECTED_MOVING_S


def _analyze() -> dict:
    track = parse_gpx(_FIXTURE.read_bytes())
    return AnalyzerV1().analyze(track)


def test_distance_matches_expected() -> None:
    result = _analyze()
    assert result["distance_meters"] == pytest.approx(_EXPECTED_DISTANCE_M, rel=0.01)


def test_moving_time_matches_expected() -> None:
    result = _analyze()
    assert result["moving_seconds"] == pytest.approx(_EXPECTED_MOVING_S, abs=2.0)


def test_elapsed_time_includes_the_segment_gap() -> None:
    result = _analyze()
    assert result["elapsed_seconds"] == pytest.approx(_EXPECTED_ELAPSED_S, abs=1.0)


def test_average_moving_speed_matches_expected_pace() -> None:
    result = _analyze()
    assert result["avg_moving_speed_mps"] == pytest.approx(_EXPECTED_AVG_SPEED_MPS, rel=0.02)


def test_splits_cover_three_kilometres_at_the_expected_pace() -> None:
    result = _analyze()
    splits = result["splits"]
    assert len(splits) == 3
    for split in splits:
        assert split["duration_seconds"] == pytest.approx(300.0, abs=5.0)
        assert split["avg_speed_mps"] == pytest.approx(_EXPECTED_AVG_SPEED_MPS, rel=0.05)


def test_elevation_gain_matches_the_climb_with_no_loss() -> None:
    result = _analyze()
    elevation = result["elevation"]
    assert elevation["gain_m"] == pytest.approx(20.0, abs=1.0)
    assert elevation["loss_m"] == pytest.approx(0.0, abs=1.0)


def test_best_efforts_cover_1k_and_are_close_to_expected_pace() -> None:
    result = _analyze()
    efforts = {e["distance_meters"]: e for e in result["best_efforts"]}
    assert 1000.0 in efforts
    assert efforts[1000.0]["duration_seconds"] == pytest.approx(300.0, abs=5.0)
    # only 3km total, so 5k/10k windows should not appear
    assert 5000.0 not in efforts
    assert 10000.0 not in efforts


def test_series_is_bounded_and_spans_the_whole_run() -> None:
    result = _analyze()
    series = result["series"]
    assert 0 < len(series) <= 301
    assert series[0]["t_s"] == 0.0
    # t_s tracks accumulated moving time (like splits/moving_seconds), not
    # wall-clock elapsed — the 90s segment gap contributes no t_s, the same
    # way it contributes no moving_seconds.
    assert series[-1]["t_s"] == pytest.approx(_EXPECTED_MOVING_S, abs=1.0)


def test_bounds_and_counts_are_populated() -> None:
    result = _analyze()
    assert result["bounds"] is not None
    assert result["point_count"] > 0
    assert result["segment_count"] == 2


def test_distance_is_never_negative() -> None:
    result = _analyze()
    assert result["distance_meters"] >= 0


def test_split_distances_sum_to_approximately_total_distance() -> None:
    result = _analyze()
    # 3 completed 1km splits should cover ~all of a 3km run.
    assert len(result["splits"]) * 1000.0 == pytest.approx(result["distance_meters"], rel=0.02)


def test_elevation_gain_is_never_negative() -> None:
    result = _analyze()
    assert result["elevation"]["gain_m"] >= 0
    assert result["elevation"]["loss_m"] >= 0
