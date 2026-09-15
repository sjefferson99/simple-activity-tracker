"""app/web/formatting.py's split-target helpers (issue #100)."""

import pytest

from app.analysis.v1 import _verdict
from app.web.formatting import format_speed_delta, format_split_target


def test_format_split_target_as_speed() -> None:
    assert format_split_target(2.7778, "speed") == "10.0 km/h"


def test_format_split_target_as_pace_default() -> None:
    assert format_split_target(2.7778, "pace") == "6:00 /km"
    assert format_split_target(2.7778, None) == "6:00 /km"


def test_format_split_target_none_is_a_dash() -> None:
    assert format_split_target(None, "speed") == "—"


def test_speed_delta_on_target_matches_verdicts_tolerance_in_speed_mode() -> None:
    """Regression: format_speed_delta used to decide "on target" via a
    near-zero absolute threshold instead of the same ±5% ratio _verdict
    (and the cell's colour class) uses — so a split _verdict called
    "on_target" could still render a nonzero correction arrow. Every case
    here is chosen to sit just inside/outside _verdict's own band."""
    assert _verdict(5.249, 5.0) == "on_target"
    assert format_speed_delta(5.249, 5.0, "speed") == "on target"

    assert _verdict(4.751, 5.0) == "on_target"
    assert format_speed_delta(4.751, 5.0, "speed") == "on target"

    assert _verdict(5.251, 5.0) == "too_fast"
    assert format_speed_delta(5.251, 5.0, "speed") != "on target"

    assert _verdict(4.749, 5.0) == "too_slow"
    assert format_speed_delta(4.749, 5.0, "speed") != "on target"


def test_speed_delta_on_target_matches_verdicts_tolerance_in_pace_mode() -> None:
    """Same regression as above, pace-formatted branch."""
    assert _verdict(5.249, 5.0) == "on_target"
    assert format_speed_delta(5.249, 5.0, "pace") == "on target"

    assert _verdict(5.251, 5.0) == "too_fast"
    assert format_speed_delta(5.251, 5.0, "pace") != "on target"


def test_speed_delta_arrow_and_direction_in_speed_mode() -> None:
    # Actual faster than target -> slow down -> down arrow, "fast".
    assert format_speed_delta(6.0, 5.0, "speed") == "▼ 3.6 km/h fast"
    # Actual slower than target -> speed up -> up arrow, "slow".
    assert format_speed_delta(4.0, 5.0, "speed") == "▲ 3.6 km/h slow"


def test_speed_delta_arrow_and_direction_in_pace_mode() -> None:
    # A faster runner has a *lower* pace number — same real-world direction
    # (too fast -> slow down -> ▼) as the speed-unit case, just derived from
    # an inverted number. 1000/6.0 ~= 166.7 s/km, 1000/5.0 = 200 s/km.
    assert format_speed_delta(6.0, 5.0, "pace") == "▼ 33 s/km fast"
    # 1000/4.0 = 250 s/km, 1000/5.0 = 200 s/km.
    assert format_speed_delta(4.0, 5.0, "pace") == "▲ 50 s/km slow"


@pytest.mark.parametrize("targets_as", ["speed", "pace"])
def test_speed_delta_empty_when_nothing_to_show(targets_as: str) -> None:
    assert format_speed_delta(5.0, None, targets_as) == ""
    assert format_speed_delta(None, 5.0, targets_as) == ""
    assert format_speed_delta(0.0, 5.0, targets_as) == ""
