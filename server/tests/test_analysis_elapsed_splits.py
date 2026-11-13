"""Issue #161: splits are timed on the elapsed clock (wall-clock since Start,
minus pauses), the same clock as the phone's Time tile, never on moving time."""

from datetime import UTC, datetime, timedelta

import pytest

from app.analysis.gpx_parser import parse_gpx
from app.analysis.track import Point, Segment, Track
from app.analysis.v1 import AnalyzerV1

_T0 = datetime(2026, 1, 1, 9, tzinfo=UTC)
_LON_PER_METER = 1 / 111195


def _at(seconds: float) -> datetime:
    return _T0 + timedelta(seconds=seconds)


def _fix(meters: float, seconds: float, speed_mps: float | None = 3.0) -> Point:
    return Point(
        lat=0.0,
        lon=meters * _LON_PER_METER,
        ele=None,
        time=_at(seconds),
        accuracy_m=5.0,
        speed_mps=speed_mps,
    )


def test_split_matches_the_phone_through_a_stand_still_and_a_pause() -> None:
    """The same run as mobile's metrics_engine_test "only a pause stops the
    split clock": 3 m/s for 200 s, standing still 60 s without pausing,
    paused 300 s, then 3 m/s again. The phone's split 1 is 265 + 409/3 s;
    the server must agree."""
    first = [_fix(s * 3.0, s) for s in range(0, 201)]
    first += [_fix(600.0, s, speed_mps=0.0) for s in range(201, 261)]
    second = [_fix(600.0 + (s - 562) * 3.0, s) for s in range(562, 761)]
    track = Track(
        segments=[Segment(points=first), Segment(points=second)],
        clock_spans=((_T0, _at(260)), (_at(560), _at(760))),
    )

    result = AnalyzerV1().analyze(track)

    splits = result["splits"]
    assert len(splits) == 1
    assert splits[0]["duration_seconds"] == pytest.approx(265 + 409 / 3, abs=0.01)
    assert result["elapsed_seconds"] == pytest.approx(460.0)
    # Moving time still excludes the stand still and the gate's held-back
    # segments; only the splits moved clocks.
    assert result["moving_seconds"] < 400


def test_time_before_the_first_fix_counts_toward_split_one() -> None:
    points = [_fix(s * 3.0, s, speed_mps=None) for s in range(8, 400)]
    with_spans = Track(segments=[Segment(points=points)], clock_spans=((_T0, _at(400)),))
    without = Track(segments=[Segment(points=points)])

    timed = AnalyzerV1().analyze(with_spans)["splits"][0]["duration_seconds"]
    fallback = AnalyzerV1().analyze(without)["splits"][0]["duration_seconds"]

    assert timed == pytest.approx(8 + 1000 / 3, abs=0.01)
    assert fallback == pytest.approx(1000 / 3, abs=0.01)


def test_time_splits_add_up_to_elapsed_including_one_closed_after_the_last_fix() -> None:
    points = [_fix(s * 3.0, s, speed_mps=None) for s in range(0, 101)]
    track = Track(segments=[Segment(points=points)], clock_spans=((_T0, _at(130)),))

    result = AnalyzerV1().analyze(track, split_type="time_min", split_value=1)

    splits = result["splits"]
    assert [s["duration_seconds"] for s in splits] == [60.0, 60.0]
    assert splits[0]["distance_m"] == pytest.approx(180.0, abs=0.01)
    # 60-100 s at 3 m/s, then nothing more before the 120 s boundary.
    assert splits[1]["distance_m"] == pytest.approx(120.0, abs=0.01)
    assert result["elapsed_seconds"] == pytest.approx(130.0)
    # The chart's time axis is the same clock, so split markers line up.
    assert splits[1]["boundary"]["t_s"] == 120.0
    assert result["series"][-1]["t_s"] == pytest.approx(100.0)


def test_an_open_last_span_ends_at_the_last_fix() -> None:
    points = [_fix(s * 3.0, s, speed_mps=None) for s in range(5, 50)]
    track = Track(segments=[Segment(points=points)], clock_spans=((_T0, None),))

    assert AnalyzerV1().analyze(track)["elapsed_seconds"] == pytest.approx(49.0)


def _gpx(clock_spans: str | None) -> bytes:
    extension = (
        f"<extensions><sat:clock_spans>{clock_spans}</sat:clock_spans></extensions>"
        if clock_spans is not None
        else ""
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1"
  xmlns:sat="https://simple-activity-tracker.local/gpx-extensions"
  version="1.1" creator="Simple Activity Tracker">
  {extension}
  <trk><trkseg>
    <trkpt lat="0" lon="0"><time>2026-01-01T09:00:05Z</time></trkpt>
    <trkpt lat="0" lon="0.0001"><time>2026-01-01T09:00:10Z</time></trkpt>
  </trkseg></trk>
</gpx>""".encode()


def test_parses_clock_spans_with_an_open_last_span() -> None:
    track = parse_gpx(
        _gpx("2026-01-01T09:00:00.000Z/2026-01-01T09:00:07.500Z;2026-01-01T09:00:09.000Z/")
    )
    assert track.clock_spans == (
        (_T0, _at(7.5)),
        (_at(9), None),
    )


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "not a span",
        "2026-01-01T09:00:00Z",
        "2026-01-01T09:00:10Z/2026-01-01T09:00:00Z",  # ends before it starts
        "2026-01-01T09:00:00Z/;2026-01-01T09:00:10Z/2026-01-01T09:00:20Z",  # open mid-list
        "2026-01-01T09:00:00Z/2026-01-01T09:00:10Z;2026-01-01T09:00:05Z/",  # overlap
    ],
)
def test_missing_or_malformed_clock_spans_fall_back_to_the_fixes(raw: str | None) -> None:
    assert parse_gpx(_gpx(raw)).clock_spans is None
