"""The app <-> server upload contract — see docs/VERSIONING.md §6 and
contract/README.md.

Every payload in contract/upload-summary/ must upload (201): the frozen
payloads real released apps send, and the golden payloads the current app
generates for each API level. For a payload at or below this server's own
API_LEVEL, every field must also be one the server actually reads: request
models use extra="ignore" (so a *future* app can't break this server), which
means a field this server doesn't know would otherwise be dropped silently.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from app.api.v1.schemas import ActivitySource, ActivitySummary, SplitSummary
from app.api_compat import API_LEVEL, MIN_APP_API_LEVEL

_CONTRACT_DIR = Path(__file__).resolve().parents[2] / "contract" / "upload-summary"
_PAYLOADS = sorted(_CONTRACT_DIR.glob("*.json"))
_LEVEL_FILE = re.compile(r"^api-level-(\d+)\.json$")


def _unknown_keys(model: type[BaseModel], data: dict[str, Any], path: str) -> list[str]:
    return [f"{path}{key}" for key in data if key not in model.model_fields]


def _ignored_fields(payload: dict[str, Any]) -> list[str]:
    ignored = _unknown_keys(ActivitySummary, payload, "")
    ignored += _unknown_keys(ActivitySource, payload.get("source", {}), "source.")
    for i, split in enumerate(payload.get("splits", [])):
        ignored += _unknown_keys(SplitSummary, split, f"splits[{i}].")
    return ignored


def test_contract_directory_has_the_expected_payloads() -> None:
    names = {path.name for path in _PAYLOADS}
    assert {"legacy-app-v1.0.0.json", "legacy-app-v1.2.4.json"} <= names
    # The current app's golden payload for this server's level must exist —
    # a new API level with no matching fixture means the app side of the
    # contract was never regenerated.
    assert f"api-level-{API_LEVEL}.json" in names


@pytest.mark.parametrize("path", _PAYLOADS, ids=lambda p: p.name)
def test_every_contract_payload_uploads(
    path: Path, app_client, auth_headers, sample_gpx_bytes
) -> None:
    response = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": path.read_text(encoding="utf-8")},
        files={"gpx": ("activity.gpx", sample_gpx_bytes, "application/gpx+xml")},
    )
    assert response.status_code == 201, response.text


@pytest.mark.parametrize("path", _PAYLOADS, ids=lambda p: p.name)
def test_server_reads_every_field_the_app_sends_at_its_level(path: Path) -> None:
    match = _LEVEL_FILE.match(path.name)
    if match is None or int(match.group(1)) > API_LEVEL:
        pytest.skip("only applies to api-level payloads at or below API_LEVEL")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert _ignored_fields(payload) == [], (
        f"{path.name} sends fields this server silently ignores — add them to the "
        "request schema (and bump API_LEVEL), or stop the app sending them"
    )


def test_unknown_request_fields_are_ignored_not_rejected(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    """A newer app will send fields this server has never heard of; a 422 here
    is exactly the failure #141 was raised to prevent."""
    payload = json.loads((_CONTRACT_DIR / "legacy-app-v1.0.0.json").read_text(encoding="utf-8"))
    payload["some_future_field"] = {"nested": True}
    payload["source"]["some_future_source_field"] = "x"
    payload["splits"][0]["some_future_split_field"] = 1.5
    response = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(payload)},
        files={"gpx": ("activity.gpx", sample_gpx_bytes, "application/gpx+xml")},
    )
    assert response.status_code == 201, response.text
    assert "some_future_field" not in response.json()["client_summary"]


def test_min_app_api_level_never_exceeds_api_level() -> None:
    assert 0 <= MIN_APP_API_LEVEL <= API_LEVEL
