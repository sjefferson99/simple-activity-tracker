"""fit_parser.py — FIT (Garmin/ANT binary) parsing, per PR 3 of issue #61's
Strava-import plan. Fixtures under tests/fixtures/sample*.fit are fully
synthetic FIT binaries built by hand from the documented FIT format (see
the fixture-generation note below) — no real GPS/personal data."""

from pathlib import Path

import pytest

from app.analysis.fit_parser import FitParseError, parse_fit

_FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_valid_fit_parses_position_and_altitude() -> None:
    data = (_FIXTURE_DIR / "sample.fit").read_bytes()
    track = parse_fit(data)

    assert track.point_count == 3
    points = track.segments[0].points
    # First point was built with no altitude field at all.
    assert points[0].ele is None
    assert points[0].lat == pytest.approx(0.0)
    assert points[0].lon == pytest.approx(0.0)
    # Second/third points carry altitude, decoded via fitparse's own
    # scale/offset handling (not hand-computed in the parser).
    assert points[1].ele == pytest.approx(100.0)
    assert points[2].ele == pytest.approx(101.6, abs=0.01)
    # Semicircle-to-degree conversion sanity: strictly increasing lat/lon
    # matching the fixture's monotonically increasing semicircle values.
    assert points[0].lat < points[1].lat < points[2].lat


def test_points_are_in_file_order_as_a_single_segment() -> None:
    data = (_FIXTURE_DIR / "sample.fit").read_bytes()
    track = parse_fit(data)
    assert len(track.segments) == 1
    times = [p.time for p in track.segments[0].points]
    assert times == sorted(times)


def test_zero_usable_points_raises() -> None:
    data = (_FIXTURE_DIR / "sample_no_points.fit").read_bytes()
    with pytest.raises(FitParseError):
        parse_fit(data)


def test_corrupt_fit_raises() -> None:
    with pytest.raises(FitParseError):
        parse_fit(b"not a fit file at all")


def test_truncated_fit_raises() -> None:
    data = (_FIXTURE_DIR / "sample.fit").read_bytes()
    with pytest.raises(FitParseError):
        parse_fit(data[: len(data) // 2])
