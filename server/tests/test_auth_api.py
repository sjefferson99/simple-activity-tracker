def test_login_with_correct_credentials_returns_a_token(app_client, admin_token) -> None:
    assert admin_token


def test_login_with_wrong_password_is_rejected(app_client, admin_token) -> None:
    response = app_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "wrong", "device_name": "x"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_login_with_unknown_email_is_rejected(app_client) -> None:
    response = app_client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "whatever", "device_name": "x"},
    )
    assert response.status_code == 401


def test_me_requires_authentication(app_client) -> None:
    response = app_client.get("/api/v1/me")
    assert response.status_code == 401


def test_me_with_bearer_token_returns_the_user(app_client, auth_headers) -> None:
    response = app_client.get("/api/v1/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["email"] == "admin@example.com"


def test_logout_revokes_the_token(app_client, auth_headers) -> None:
    response = app_client.post("/api/v1/auth/logout", headers=auth_headers)
    assert response.status_code == 204

    response = app_client.get("/api/v1/me", headers=auth_headers)
    assert response.status_code == 401


def test_devices_lists_and_revokes(app_client, auth_headers) -> None:
    response = app_client.get("/api/v1/me/devices", headers=auth_headers)
    assert response.status_code == 200
    devices = response.json()
    assert len(devices) == 1

    device_id = devices[0]["id"]
    response = app_client.delete(f"/api/v1/me/devices/{device_id}", headers=auth_headers)
    assert response.status_code == 204

    # the just-revoked device was also the one authenticating this request
    response = app_client.get("/api/v1/me", headers=auth_headers)
    assert response.status_code == 401


def test_revoking_someone_elses_device_404s(app_client, auth_headers) -> None:
    response = app_client.delete("/api/v1/me/devices/not-a-real-id", headers=auth_headers)
    assert response.status_code == 404


def test_change_password_invalidates_other_sessions_but_not_this_one(
    app_client, auth_headers
) -> None:
    login2 = app_client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin@example.com",
            "password": "admin-password-123",
            "device_name": "second",
        },
    )
    other_headers = {"Authorization": f"Bearer {login2.json()['token']}"}
    assert app_client.get("/api/v1/me", headers=other_headers).status_code == 200

    response = app_client.put(
        "/api/v1/me/password",
        headers=auth_headers,
        json={"current_password": "admin-password-123", "new_password": "new-password-456"},
    )
    assert response.status_code == 204

    assert app_client.get("/api/v1/me", headers=auth_headers).status_code == 200
    assert app_client.get("/api/v1/me", headers=other_headers).status_code == 401


def test_change_password_with_wrong_current_password_is_rejected(app_client, auth_headers) -> None:
    response = app_client.put(
        "/api/v1/me/password",
        headers=auth_headers,
        json={"current_password": "not-the-password", "new_password": "new-password-456"},
    )
    assert response.status_code == 401


def test_change_password_with_short_new_password_is_rejected(app_client, auth_headers) -> None:
    response = app_client.put(
        "/api/v1/me/password",
        headers=auth_headers,
        json={"current_password": "admin-password-123", "new_password": "short"},
    )
    assert response.status_code == 422
