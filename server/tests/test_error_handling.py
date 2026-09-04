"""R6: error responses follow one consistent contract per client type —
JSON {"error": {...}} for API/htmx clients, an HTML page for a plain browser
navigation. See docs/SERVER-PRODUCTION-PLAN.md R6."""

import json

from fastapi.testclient import TestClient

from tests.conftest import make_summary


def _login_cookie_client(app_client, email: str, password: str) -> TestClient:
    response = app_client.post(
        "/login",
        headers={"X-Requested-With": "htmx"},
        data={"email": email, "password": password},
    )
    assert response.status_code == 200
    return app_client


def test_api_422_uses_the_error_contract_shape(app_client, auth_headers) -> None:
    response = app_client.post(
        "/api/v1/admin/users",
        headers=auth_headers,
        json={"email": "not-an-email", "display_name": "", "password": "x"},
    )
    assert response.status_code == 422
    body = response.json()
    assert "error" in body
    assert "code" in body["error"]
    assert "message" in body["error"]


def test_browser_422_renders_html_not_json(app_client, auth_headers) -> None:
    response = app_client.post(
        "/api/v1/admin/users",
        headers={**auth_headers, "Accept": "text/html"},
        json={"email": "not-an-email", "display_name": "", "password": "x"},
    )
    # This is still an /api/ path, so it must stay JSON even with an HTML
    # Accept header — only non-API paths get the HTML error page.
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")


def test_admin_users_page_404_renders_html_for_non_admin(app_client, auth_headers) -> None:
    create = app_client.post(
        "/api/v1/admin/users",
        headers=auth_headers,
        json={
            "email": "member@example.com",
            "display_name": "Member",
            "password": "member-password-123",
        },
    )
    assert create.status_code == 201

    client = _login_cookie_client(app_client, "member@example.com", "member-password-123")
    response = client.get("/admin/users")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "Not found" in response.text


def test_register_disabled_404_renders_html(app_client) -> None:
    response = app_client.get("/register")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")


def test_unhandled_exception_returns_json_error_for_api_client(app_client, auth_headers) -> None:
    app_client.app.get("/api/v1/__boom")(lambda: (_ for _ in ()).throw(RuntimeError("kaboom")))
    client = TestClient(app_client.app, raise_server_exceptions=False)
    client.cookies = app_client.cookies

    response = client.get("/api/v1/__boom", headers=auth_headers)
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "correlation_id" in body["error"]
    assert "X-Correlation-Id" in response.headers


def test_unhandled_exception_returns_html_error_page_for_browser(app_client) -> None:
    app_client.app.get("/__boom_web")(lambda: (_ for _ in ()).throw(RuntimeError("kaboom")))
    client = TestClient(app_client.app, raise_server_exceptions=False)
    client.cookies = app_client.cookies

    response = client.get("/__boom_web")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("text/html")
    assert "X-Correlation-Id" in response.headers


def test_unhandled_exception_htmx_fragment_request_gets_json(app_client) -> None:
    app_client.app.get("/__boom_htmx")(lambda: (_ for _ in ()).throw(RuntimeError("kaboom")))
    client = TestClient(app_client.app, raise_server_exceptions=False)
    client.cookies = app_client.cookies

    response = client.get("/__boom_htmx", headers={"hx-request": "true"})
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")


def test_activity_summary_missing_avg_speed_renders_activity_detail(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    summary = make_summary()
    del summary["avg_speed_mps"]
    upload = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(summary)},
        files={"gpx": ("activity.gpx", sample_gpx_bytes, "application/gpx+xml")},
    )
    assert upload.status_code == 201
    activity_id = upload.json()["id"]

    client = _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = client.get(f"/activities/{activity_id}")
    assert response.status_code == 200
    assert "—" in response.text
