"""sat:pressure_hpa (issue #184): the phone's barometer reading per fix. Parsed
for elevation work; nothing in the analysis reads it yet."""

import pytest

from app.analysis.gpx_parser import parse_gpx
from app.analysis.v1 import AnalyzerV1


def _gpx(point_extensions: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Simple Activity Tracker"
     xmlns="http://www.topografix.com/GPX/1/1"
     xmlns:sat="https://simple-activity-tracker.local/gpx-extensions">
  <trk><trkseg>
    <trkpt lat="51.5" lon="-0.1"><ele>20</ele><time>2026-10-31T09:00:00Z</time>
      <extensions><sat:accuracy>4.0</sat:accuracy><sat:has_accuracy>true</sat:has_accuracy>
      {point_extensions}</extensions></trkpt>
    <trkpt lat="51.5003" lon="-0.1"><ele>21</ele><time>2026-10-31T09:00:10Z</time>
      <extensions><sat:accuracy>4.0</sat:accuracy><sat:has_accuracy>true</sat:has_accuracy>
      {point_extensions}</extensions></trkpt>
  </trkseg></trk>
</gpx>""".encode()


def _first_pressure(point_extensions: str) -> float | None:
    return parse_gpx(_gpx(point_extensions)).segments[0].points[0].pressure_hpa


def test_reads_the_reading() -> None:
    assert _first_pressure("<sat:pressure_hpa>1013.25</sat:pressure_hpa>") == 1013.25


def test_absent_is_none() -> None:
    assert _first_pressure("") is None


@pytest.mark.parametrize("text", ["", "abc", "nan", "inf", "0", "-5"])
def test_unusable_value_is_none_and_never_fails_the_upload(text: str) -> None:
    assert _first_pressure(f"<sat:pressure_hpa>{text}</sat:pressure_hpa>") is None


def test_pressure_does_not_change_the_analysis() -> None:
    with_pressure = parse_gpx(_gpx("<sat:pressure_hpa>1013.25</sat:pressure_hpa>"))
    without = parse_gpx(_gpx(""))
    assert AnalyzerV1().analyze(with_pressure) == AnalyzerV1().analyze(without)
