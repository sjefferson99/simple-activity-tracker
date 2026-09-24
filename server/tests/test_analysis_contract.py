"""The analysis.result fields the app reads — contract/analysis-result/app-reads.json,
docs/VERSIONING.md §6.

analysis.result is ``dict[str, Any]`` in openapi.json, so the API-level guard
and oasdiff can't see its shape. Released apps cast some of its fields with no
fallback, so renaming one, dropping one, or changing its type would crash
their activity screen. This checks the analyzer's real output instead.
"""

import json
from pathlib import Path
from typing import Any

from tests.conftest import upload_sample_activity

_CONTRACT = json.loads(
    (
        Path(__file__).resolve().parents[2] / "contract" / "analysis-result" / "app-reads.json"
    ).read_text(encoding="utf-8")
)


def _type_ok(value: Any, expected: str) -> bool:
    for kind in expected.split("|"):
        if kind == "null" and value is None:
            return True
        if kind == "number" and isinstance(value, int | float) and not isinstance(value, bool):
            return True
        if kind == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if kind == "string" and isinstance(value, str):
            return True
        if kind == "object" and isinstance(value, dict):
            return True
        if kind == "array" and isinstance(value, list):
            return True
    return False


def _violations(data: dict[str, Any], spec: dict[str, str], path: str) -> list[str]:
    problems = []
    for key, expected in spec.items():
        if key not in data:
            if "optional" not in expected.split("|"):
                problems.append(f"{path}{key}: missing")
            continue
        if not _type_ok(data[key], expected):
            problems.append(f"{path}{key}: expected {expected}, got {data[key]!r}")
    return problems


def check_against_contract(result: dict[str, Any]) -> list[str]:
    problems = _violations(result, _CONTRACT["result"], "")
    if isinstance(result.get("elevation"), dict):
        problems += _violations(result["elevation"], _CONTRACT["elevation"], "elevation.")
    for i, effort in enumerate(result.get("best_efforts") or []):
        problems += _violations(effort, _CONTRACT["best_efforts[]"], f"best_efforts[{i}].")
    for i, split in enumerate(result.get("splits") or []):
        problems += _violations(split, _CONTRACT["splits[]"], f"splits[{i}].")
    return problems


def test_analysis_result_has_every_field_the_app_reads(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    created = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    response = app_client.get(f"/api/v1/activities/{created['id']}/analysis", headers=auth_headers)
    assert response.status_code == 200
    result = response.json()["result"]
    # The sample is a 3 km run: splits and best efforts must be non-empty, or
    # their per-item fields would never actually be checked.
    assert result["splits"] and result["best_efforts"]
    assert check_against_contract(result) == []


def test_contract_checker_catches_a_broken_result() -> None:
    """Guards the checker itself: a renamed key and a float index must fail."""
    broken = {
        "distance_meters": 1.0,
        "elapsed_seconds": 1.0,
        "moving_seconds": 1.0,
        "avg_moving_speed_mps": None,
        "elevation": {"gain_m": None, "loss_m": None},
        "best_efforts": [{"distance_m": 1000.0, "duration_seconds": 300.0}],
        "splits": [{"index": 1.0, "distance_m": 1000.0, "duration_seconds": 300.0}],
        "split_type": "distance_km",
    }
    problems = check_against_contract(broken)
    assert "best_efforts[0].distance_meters: missing" in problems
    assert any(p.startswith("splits[0].index: expected integer") for p in problems)
