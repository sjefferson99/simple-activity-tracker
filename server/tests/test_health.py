def test_healthz_reports_ok_with_a_migrated_db(app_client) -> None:
    response = app_client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"


def test_healthz_omits_version_by_default(app_client) -> None:
    response = app_client.get("/healthz")

    assert response.status_code == 200
    assert "version" not in response.json()


def test_healthz_includes_version_when_docs_enabled(app_client, monkeypatch) -> None:
    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("SR_ENABLE_API_DOCS", "true")
    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    with TestClient(create_app()) as client:
        response = client.get("/healthz")

    get_settings.cache_clear()
    assert response.status_code == 200
    assert "version" in response.json()
