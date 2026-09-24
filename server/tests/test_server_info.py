"""GET /api/v1/server-info and the web footer — see docs/VERSIONING.md §1."""

import importlib
import json
from pathlib import Path

import app.version
from app.api_compat import API_LEVEL, MIN_APP_API_LEVEL

HTMX_HEADERS = {"X-Requested-With": "htmx"}


def test_server_info_requires_sign_in(app_client) -> None:
    assert app_client.get("/api/v1/server-info").status_code == 401


def test_server_info_reports_version_and_levels(app_client, auth_headers) -> None:
    response = app_client.get("/api/v1/server-info", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {
        # No SAT_BUILD_VERSION in the test environment.
        "version": "dev",
        "api_level": API_LEVEL,
        "min_app_api_level": MIN_APP_API_LEVEL,
    }


def test_build_version_comes_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("SAT_BUILD_VERSION", "1.3.0+4.gabc1234")
    try:
        assert importlib.reload(app.version).APP_VERSION == "1.3.0+4.gabc1234"
    finally:
        monkeypatch.delenv("SAT_BUILD_VERSION")
        importlib.reload(app.version)


def test_openapi_version_is_the_api_level() -> None:
    """CI's API-level check reads info.version from the committed spec."""
    spec_path = Path(__file__).resolve().parents[1] / "openapi.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    assert spec["info"]["version"] == str(API_LEVEL)


def test_web_footer_shows_version_to_signed_in_users(app_client, admin_token) -> None:
    del admin_token  # only needed to create admin@example.com
    login = app_client.post(
        "/login",
        headers=HTMX_HEADERS,
        data={"email": "admin@example.com", "password": "admin-password-123"},
    )
    assert login.status_code == 200
    response = app_client.get("/")
    assert response.status_code == 200
    assert f"Simple Activity Tracker dev · API level {API_LEVEL}" in response.text


def test_web_footer_hidden_from_anonymous_visitors(app_client) -> None:
    response = app_client.get("/login")
    assert response.status_code == 200
    assert "site-footer" not in response.text
    assert "API level" not in response.text
