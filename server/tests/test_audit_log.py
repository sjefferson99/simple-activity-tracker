"""R5 (docs/SERVER-PRODUCTION-PLAN.md): security-relevant actions must leave
an audit trail — login success/failure, token/session revocation, and admin
user/activity actions. Never a token, cookie, or password in the log line."""

import logging

from tests.conftest import upload_sample_activity


def test_login_success_is_audited(app_client, admin_token, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="app.audit"):
        response = app_client.post(
            "/api/v1/auth/login",
            json={
                "email": "admin@example.com",
                "password": "admin-password-123",
                "device_name": "audit-test",
            },
        )
    assert response.status_code == 200
    messages = [r.message for r in caplog.records if r.name == "app.audit"]
    assert any("event=login.success" in m for m in messages)
    assert not any("admin-password-123" in m for m in messages)


def test_login_failure_is_audited_without_the_password(app_client, admin_token, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="app.audit"):
        response = app_client.post(
            "/api/v1/auth/login",
            json={
                "email": "admin@example.com",
                "password": "wrong-password-entirely",
                "device_name": "audit-test",
            },
        )
    assert response.status_code == 401
    messages = [r.message for r in caplog.records if r.name == "app.audit"]
    assert any("event=login.failure" in m and "email=admin@example.com" in m for m in messages)
    assert not any("wrong-password-entirely" in m for m in messages)


def test_web_login_success_is_audited(app_client, admin_token, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="app.audit"):
        response = app_client.post(
            "/login",
            headers={"X-Requested-With": "htmx"},
            data={"email": "admin@example.com", "password": "admin-password-123"},
        )
    assert response.status_code == 200
    messages = [r.message for r in caplog.records if r.name == "app.audit"]
    assert any("event=login.success" in m for m in messages)


def test_device_token_revocation_is_audited(app_client, admin_token, auth_headers, caplog) -> None:
    devices = app_client.get("/api/v1/me/devices", headers=auth_headers).json()
    device_id = devices[0]["id"]
    with caplog.at_level(logging.INFO, logger="app.audit"):
        response = app_client.delete(f"/api/v1/me/devices/{device_id}", headers=auth_headers)
    assert response.status_code == 204
    messages = [r.message for r in caplog.records if r.name == "app.audit"]
    assert any("event=token.revoked" in m and f"target_id={device_id}" in m for m in messages)


def test_admin_create_user_is_audited(app_client, auth_headers, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="app.audit"):
        response = app_client.post(
            "/api/v1/admin/users",
            headers=auth_headers,
            json={
                "email": "newuser@example.com",
                "display_name": "New User",
                "password": "a-strong-password",
                "is_admin": False,
            },
        )
    assert response.status_code == 201
    messages = [r.message for r in caplog.records if r.name == "app.audit"]
    assert any("event=user.created" in m and "a-strong-password" not in m for m in messages)


def test_admin_delete_user_is_audited(app_client, auth_headers, caplog) -> None:
    created = app_client.post(
        "/api/v1/admin/users",
        headers=auth_headers,
        json={
            "email": "todelete@example.com",
            "display_name": "To Delete",
            "password": "a-strong-password",
            "is_admin": False,
        },
    ).json()

    with caplog.at_level(logging.INFO, logger="app.audit"):
        response = app_client.delete(f"/api/v1/admin/users/{created['id']}", headers=auth_headers)
    assert response.status_code == 204
    messages = [r.message for r in caplog.records if r.name == "app.audit"]
    assert any("event=user.deleted" in m and f"target_id={created['id']}" in m for m in messages)


def test_activity_delete_is_audited(app_client, auth_headers, sample_gpx_bytes, caplog) -> None:
    created = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    with caplog.at_level(logging.INFO, logger="app.audit"):
        response = app_client.delete(f"/api/v1/activities/{created['id']}", headers=auth_headers)
    assert response.status_code == 204
    messages = [r.message for r in caplog.records if r.name == "app.audit"]
    assert any(
        "event=activity.deleted" in m and f"target_id={created['id']}" in m for m in messages
    )
