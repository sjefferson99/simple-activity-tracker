"""The GPX the app uploads — contract/gpx/, docs/VERSIONING.md §6.

Each contract/gpx/<name>.gpx is written by the app's real GPX writer, with a
<name>.expected.json stating what the app means by it. The server must extract
exactly that (split plan, targets, per-point accuracy/speed) and produce an
analysis with every field the app reads. openapi.json can't describe the
sat: extensions, so this is the only thing that notices if either side changes
their format.
"""

import json
from pathlib import Path

import pytest

from app.analysis.gpx_parser import parse_gpx, parse_split_plan
from tests.conftest import make_summary
from tests.test_analysis_contract import check_against_contract

_GPX_DIR = Path(__file__).resolve().parents[2] / "contract" / "gpx"
_CASES = sorted(_GPX_DIR.glob("*.gpx"))


def _expected(gpx_path: Path) -> dict:
    expected_path = gpx_path.with_name(gpx_path.stem + ".expected.json")
    return json.loads(expected_path.read_text(encoding="utf-8"))


def test_contract_gpx_files_exist() -> None:
    assert {p.name for p in _CASES} >= {"custom-plan.gpx", "rolling-target.gpx"}


@pytest.mark.parametrize("gpx_path", _CASES, ids=lambda p: p.name)
def test_server_reads_what_the_app_means(gpx_path: Path) -> None:
    data = gpx_path.read_bytes()
    expected = _expected(gpx_path)

    plan = parse_split_plan(data)
    assert plan is not None
    assert plan.split_type == expected["split_type"]
    assert plan.split_value == expected["split_value"]
    assert plan.rolling_target_mps == expected["rolling_target_mps"]
    assert [list(pair) for pair in plan.custom_splits] == expected["custom_splits"]
    assert plan.targets_as == expected["targets_as"]

    track = parse_gpx(data)
    points = [p for segment in track.segments for p in segment.points]
    assert len(points) == expected["point_count"]
    assert points[0].accuracy_m == expected["first_point"]["accuracy_m"]
    assert points[0].speed_mps == expected["first_point"]["speed_mps"]


@pytest.mark.parametrize("gpx_path", _CASES, ids=lambda p: p.name)
def test_contract_gpx_uploads_and_analyses_to_the_app_contract(
    gpx_path: Path, app_client, auth_headers
) -> None:
    response = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(make_summary())},
        files={"gpx": (gpx_path.name, gpx_path.read_bytes(), "application/gpx+xml")},
    )
    assert response.status_code == 201, response.text
    analysis = response.json()["analysis"]
    assert analysis["status"] == "done"
    assert check_against_contract(analysis["result"]) == []
