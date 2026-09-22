"""Route-level tests for app/web/split_configs.py (issue #126) — see
docs/SPLIT-CONFIGS-PLAN.md §6 item 3. Manually verified end-to-end against a
real running dev server before writing these (curl session: create/edit/
delete, name-collision + overwrite, invalid-plan rendering, CSRF, signed-out
redirect — all behaved as intended); this file locks that behaviour in.
"""

import re

HTMX_HEADERS = {"X-Requested-With": "htmx"}

_EDIT_LINK_RE = re.compile(r"/split-configs/([0-9a-f-]{36})/edit")


def _edit_ids(list_html: str) -> list[str]:
    return _EDIT_LINK_RE.findall(list_html)


def _login_cookie_client(
    app_client, email: str = "admin@example.com", password: str = "admin-password-123"
):
    response = app_client.post(
        "/login", headers=HTMX_HEADERS, data={"email": email, "password": password}
    )
    assert response.status_code == 200
    return app_client


def _create(client, **fields):
    payload = {
        "config_id": "",
        "name": "5k tempo",
        "split_type": "distance_km",
        "split_value": "1",
        "targets_as": "pace",
        "plan_kind": "rolling",
        "rolling_target": "5:00",
    }
    payload.update(fields)
    return client.post("/split-configs", headers=HTMX_HEADERS, data=payload)


class TestSignedOut:
    def test_list_redirects_to_login(self, app_client):
        response = app_client.get("/split-configs", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_new_form_redirects_to_login(self, app_client):
        response = app_client.get("/split-configs/new", follow_redirects=False)
        assert response.status_code == 303


class TestCsrf:
    def test_create_without_htmx_header_is_rejected(self, app_client, auth_headers):
        client = _login_cookie_client(app_client)
        response = client.post(
            "/split-configs",
            data={
                "config_id": "",
                "name": "x",
                "split_type": "distance_km",
                "split_value": "1",
                "targets_as": "pace",
                "plan_kind": "rolling",
                "rolling_target": "",
            },
        )
        assert response.status_code == 403

    def test_delete_without_htmx_header_is_rejected(self, app_client, auth_headers):
        client = _login_cookie_client(app_client)
        response = client.delete("/split-configs/some-id")
        assert response.status_code == 403


class TestListAndRender:
    def test_empty_list_renders(self, app_client, auth_headers):
        client = _login_cookie_client(app_client)
        response = client.get("/split-configs")
        assert response.status_code == 200
        assert "No saved split configs yet" in response.text

    def test_new_form_renders(self, app_client, auth_headers):
        client = _login_cookie_client(app_client)
        response = client.get("/split-configs/new")
        assert response.status_code == 200
        assert 'id="split-config-form"' in response.text


class TestCreateRollingPlan:
    def test_create_with_target_shows_summary_in_list(self, app_client, auth_headers):
        client = _login_cookie_client(app_client)
        response = _create(client)
        assert response.status_code == 200
        assert response.headers["hx-redirect"] == "/split-configs"

        listed = client.get("/split-configs")
        assert "5k tempo" in listed.text
        assert "Rolling, every 1 km @ 5:00 /km" in listed.text

    def test_create_without_target(self, app_client, auth_headers):
        client = _login_cookie_client(app_client)
        response = _create(client, name="Easy run", rolling_target="")
        assert response.status_code == 200
        listed = client.get("/split-configs")
        assert "Rolling, every 1 km" in listed.text

    def test_create_speed_target(self, app_client, auth_headers):
        client = _login_cookie_client(app_client)
        response = _create(client, name="Speed target", targets_as="speed", rolling_target="12.0")
        assert response.status_code == 200
        listed = client.get("/split-configs")
        assert "12.0 km/h" in listed.text


class TestValidationErrors:
    def test_invalid_split_value_shows_error(self, app_client, auth_headers):
        client = _login_cookie_client(app_client)
        response = _create(client, split_value="0")
        assert response.status_code == 400
        assert "error-banner" in response.text

    def test_invalid_pace_format_shows_error(self, app_client, auth_headers):
        client = _login_cookie_client(app_client)
        response = _create(client, rolling_target="not-a-pace")
        assert response.status_code == 400
        assert "Enter a pace as mm:ss" in response.text

    def test_blank_name_shows_error(self, app_client, auth_headers):
        client = _login_cookie_client(app_client)
        response = _create(client, name="   ")
        assert response.status_code == 400

    def test_empty_custom_plan_shows_error(self, app_client, auth_headers):
        client = _login_cookie_client(app_client)
        response = _create(
            client,
            name="Empty custom",
            plan_kind="custom",
            rolling_target="",
        )
        assert response.status_code == 400
        assert "Add at least one custom split" in response.text


class TestCustomPlan:
    def test_create_custom_plan_round_trips_through_edit(self, app_client, auth_headers):
        client = _login_cookie_client(app_client)
        response = client.post(
            "/split-configs",
            headers=HTMX_HEADERS,
            data={
                "config_id": "",
                "name": "Intervals",
                "split_type": "time_min",
                "split_value": "1",
                "targets_as": "speed",
                "plan_kind": "custom",
                "rolling_target": "",
                "split_size": ["1:30", "1:00", "1:30"],
                "split_target": ["8.0", "6.0", ""],
            },
        )
        assert response.status_code == 200

        listed = client.get("/split-configs")
        assert "Custom, 3 splits" in listed.text

        config_id = _edit_ids(listed.text)[0]
        edit_page = client.get(f"/split-configs/{config_id}/edit")
        assert edit_page.status_code == 200
        assert 'value="1:30"' in edit_page.text
        assert 'value="8"' in edit_page.text
        assert 'value="1:00"' in edit_page.text
        assert 'value="6"' in edit_page.text
        assert 'name="plan_kind" value="custom" checked' in edit_page.text

    def test_add_custom_row_endpoint_appends_a_blank_row(self, app_client, auth_headers):
        client = _login_cookie_client(app_client)
        response = client.post(
            "/split-configs/custom-rows",
            headers=HTMX_HEADERS,
            data={
                "config_id": "",
                "name": "x",
                "split_type": "time_min",
                "split_value": "1",
                "targets_as": "pace",
                "plan_kind": "custom",
                "rolling_target": "",
                "split_size": ["1:30"],
                "split_target": ["5:00"],
            },
        )
        assert response.status_code == 200
        assert response.text.count('name="split_size"') == 2

    def test_remove_custom_row_endpoint_removes_the_named_row(self, app_client, auth_headers):
        client = _login_cookie_client(app_client)
        response = client.post(
            "/split-configs/custom-rows",
            headers=HTMX_HEADERS,
            data={
                "config_id": "",
                "name": "x",
                "split_type": "time_min",
                "split_value": "1",
                "targets_as": "pace",
                "plan_kind": "custom",
                "rolling_target": "",
                "split_size": ["1:30", "1:00"],
                "split_target": ["5:00", "4:00"],
                "remove_row": "0",
            },
        )
        assert response.status_code == 200
        assert response.text.count('name="split_size"') == 1
        assert 'value="1:00"' in response.text


class TestNameCollision:
    def test_create_duplicate_name_is_409_with_replace_button(self, app_client, auth_headers):
        client = _login_cookie_client(app_client)
        _create(client)
        response = _create(client, split_value="2")
        assert response.status_code == 409
        assert "already exists" in response.text
        assert "Replace it" in response.text

    def test_overwrite_replaces_existing_config(self, app_client, auth_headers):
        client = _login_cookie_client(app_client)
        _create(client)
        response = _create(client, split_value="3", rolling_target="", overwrite="true")
        assert response.status_code == 200

        listed = client.get("/split-configs")
        # "5k tempo" legitimately appears twice per row (the visible cell and
        # the delete button's hx-confirm text) — one *row* is what matters.
        assert listed.text.count("<td>5k tempo</td>") == 1
        assert "every 3 km" in listed.text

    def test_rename_into_collision_is_409(self, app_client, auth_headers):
        client = _login_cookie_client(app_client)
        _create(client, name="First")
        _create(client, name="Second")

        listed = client.get("/split-configs")
        ids = _edit_ids(listed.text)
        # Find Second's id by loading each edit page.
        second_id = None
        for config_id in ids:
            edit_page = client.get(f"/split-configs/{config_id}/edit")
            if 'value="Second"' in edit_page.text:
                second_id = config_id
                break
        assert second_id is not None

        response = client.post(
            "/split-configs",
            headers=HTMX_HEADERS,
            data={
                "config_id": second_id,
                "name": "First",
                "split_type": "distance_km",
                "split_value": "1",
                "targets_as": "pace",
                "plan_kind": "rolling",
                "rolling_target": "",
            },
        )
        assert response.status_code == 409


class TestDelete:
    def test_delete_removes_config_from_list(self, app_client, auth_headers):
        client = _login_cookie_client(app_client)
        _create(client)
        listed = client.get("/split-configs")
        config_id = _edit_ids(listed.text)[0]

        response = client.delete(f"/split-configs/{config_id}", headers=HTMX_HEADERS)
        assert response.status_code == 200
        assert "5k tempo" not in response.text

    def test_delete_missing_config_is_a_noop_200(self, app_client, auth_headers):
        client = _login_cookie_client(app_client)
        response = client.delete(
            "/split-configs/00000000-0000-0000-0000-000000000000", headers=HTMX_HEADERS
        )
        assert response.status_code == 200


class TestPerUserIsolation:
    def test_other_user_does_not_see_configs_in_list(self, app_client, auth_headers):
        client = _login_cookie_client(app_client)
        _create(client)

        from datetime import UTC, datetime

        from app.auth.passwords import hash_password
        from app.db import get_session_factory
        from app.models.user import User
        from app.repositories.users import SqlAlchemyUserRepository

        with get_session_factory()() as session:
            now = datetime.now(UTC)
            other = User(
                email="other-web@example.com",
                password_hash=hash_password("other-password-123"),
                display_name="Other",
                is_admin=False,
                sessions_invalidated_at=now,
                created_at=now,
            )
            SqlAlchemyUserRepository(session).add(other)
            session.commit()

        other_client = _login_cookie_client(
            app_client, "other-web@example.com", "other-password-123"
        )
        listed = other_client.get("/split-configs")
        assert "5k tempo" not in listed.text
        assert "No saved split configs yet" in listed.text
