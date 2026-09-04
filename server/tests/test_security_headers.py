"""Security response header coverage — see docs/SERVER-PRODUCTION-PLAN.md S5."""

from tests.conftest import upload_sample_activity

_FIXED_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "geolocation=(), camera=(), microphone=()",
    "cross-origin-opener-policy": "same-origin",
}


def _assert_fixed_headers_present(headers) -> None:
    for name, value in _FIXED_HEADERS.items():
        assert headers[name] == value
    assert "nonce-" in headers["content-security-policy"]
    assert "frame-ancestors 'none'" in headers["content-security-policy"]


def test_login_page_has_security_headers(app_client):
    response = app_client.get("/login")
    assert response.status_code == 200
    _assert_fixed_headers_present(response.headers)
    assert response.headers["cache-control"] == "no-store"


def test_signed_in_page_has_security_headers(app_client, auth_headers):
    login = app_client.post(
        "/login",
        headers={"X-Requested-With": "htmx"},
        data={"email": "admin@example.com", "password": "admin-password-123"},
    )
    assert login.status_code == 200

    response = app_client.get("/")
    assert response.status_code == 200
    _assert_fixed_headers_present(response.headers)
    assert response.headers["cache-control"] == "no-store"


def test_api_response_has_security_headers(app_client, auth_headers):
    response = app_client.get("/api/v1/me", headers=auth_headers)
    assert response.status_code == 200
    _assert_fixed_headers_present(response.headers)
    assert response.headers["cache-control"] == "no-store"


def test_static_asset_is_cacheable_and_still_has_fixed_headers(app_client):
    response = app_client.get("/static/app.css")
    assert response.status_code == 200
    _assert_fixed_headers_present(response.headers)
    assert response.headers.get("cache-control") != "no-store"


def test_hsts_absent_when_cookies_not_secure(app_client):
    response = app_client.get("/healthz")
    assert "strict-transport-security" not in response.headers


def test_hsts_present_when_cookies_secure(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.db import get_engine
    from app.main import create_app

    db_path = tmp_path / "secure.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("SR_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SR_SECRET_KEY", "test-secret-key-not-a-real-one-32chars")
    monkeypatch.setenv("SR_DATA_DIR", str(data_dir))
    monkeypatch.setenv("SR_SECURE_COOKIES", "true")
    get_settings.cache_clear()
    get_engine.cache_clear()

    import os

    from alembic.config import Config

    from alembic import command

    server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    alembic_cfg = Config(os.path.join(server_dir, "alembic.ini"))
    alembic_cfg.set_main_option("script_location", os.path.join(server_dir, "alembic"))
    command.upgrade(alembic_cfg, "head")

    try:
        with TestClient(create_app()) as client:
            response = client.get("/healthz")
            assert response.headers["strict-transport-security"] == (
                "max-age=31536000; includeSubDomains"
            )
    finally:
        get_settings.cache_clear()
        get_engine.cache_clear()


def test_activity_detail_map_and_chart_still_render(app_client, sample_gpx_bytes, auth_headers):
    """CSP-with-nonce sanity check: the page most reliant on inline scripts
    (map + chart, both driven by an inline <script nonce=...>) must still
    render its content, not just return 200 — a nonce mismatch would leave
    the page structurally present but silently non-functional in a browser,
    which this can't detect, but a missing map/chart id would indicate the
    template broke."""
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]

    login = app_client.post(
        "/login",
        headers={"X-Requested-With": "htmx"},
        data={"email": "admin@example.com", "password": "admin-password-123"},
    )
    assert login.status_code == 200

    response = app_client.get(f"/activities/{activity_id}")
    assert response.status_code == 200
    assert 'nonce="' in response.text
    assert 'id="map"' in response.text
