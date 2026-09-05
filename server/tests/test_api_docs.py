"""S7 in docs/SERVER-PRODUCTION-PLAN.md: /api/docs and /api/openapi.json are
public and disclose version info by default — undesirable outside a LAN."""

from fastapi.testclient import TestClient


def test_docs_and_openapi_404_by_default(app_client) -> None:
    assert app_client.get("/api/docs").status_code == 404
    assert app_client.get("/api/openapi.json").status_code == 404


def test_docs_and_openapi_available_when_enabled(app_client, monkeypatch) -> None:
    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("SR_ENABLE_API_DOCS", "true")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        docs_response = client.get("/api/docs")
        openapi_response = client.get("/api/openapi.json")

    get_settings.cache_clear()
    assert docs_response.status_code == 200
    assert openapi_response.status_code == 200
    assert openapi_response.json()["info"]["title"] == "Simple Activity Tracker Server"
