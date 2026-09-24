"""API tests for saved split configs (issue #126) — see
docs/SPLIT-CONFIGS-PLAN.md §6 item 2. Model/repository/SplitPlanIn
validation tests live in test_split_configs_model.py; this file exercises
the real /api/v1/split-configs routes end to end.
"""

from datetime import UTC, datetime


def _other_user_headers(app_client, email: str = "other-configs@example.com") -> dict[str, str]:
    """Creates a second account and returns its bearer auth headers — mirrors
    the pattern in test_tags.py::_other_user_headers."""
    from app.auth.passwords import hash_password
    from app.db import get_session_factory
    from app.models.user import User
    from app.repositories.users import SqlAlchemyUserRepository

    with get_session_factory()() as session:
        now = datetime.now(UTC)
        other = User(
            email=email,
            password_hash=hash_password("other-password-123"),
            display_name="Other",
            is_admin=False,
            sessions_invalidated_at=now,
            created_at=now,
        )
        SqlAlchemyUserRepository(session).add(other)
        session.commit()

    login = app_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "other-password-123", "device_name": "x"},
    )
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _rolling_plan(**overrides: object) -> dict[str, object]:
    plan = {
        "split_type": "distance_km",
        "split_value": 1,
        "rolling_target_mps": 2.5,
        "custom_splits": [],
        "targets_as": "pace",
    }
    plan.update(overrides)
    return plan


def _custom_plan(**overrides: object) -> dict[str, object]:
    plan = {
        "split_type": "time_min",
        "split_value": 1,
        "rolling_target_mps": None,
        "custom_splits": [[90.0, 4.0], [60.0, 6.0], [90.0, None]],
        "targets_as": "speed",
    }
    plan.update(overrides)
    return plan


class TestListAndGet:
    def test_list_is_empty_initially(self, app_client, auth_headers):
        response = app_client.get("/api/v1/split-configs", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == {"configs": []}

    def test_list_and_get_after_create(self, app_client, auth_headers):
        create = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "5k tempo", "plan": _rolling_plan()},
        )
        assert create.status_code == 200
        config_id = create.json()["id"]

        listed = app_client.get("/api/v1/split-configs", headers=auth_headers)
        assert listed.status_code == 200
        assert [c["name"] for c in listed.json()["configs"]] == ["5k tempo"]

        got = app_client.get(f"/api/v1/split-configs/{config_id}", headers=auth_headers)
        assert got.status_code == 200
        body = got.json()
        assert body["name"] == "5k tempo"
        assert body["plan"]["rolling_target_mps"] == 2.5
        assert body["plan"]["split_type"] == "distance_km"
        assert body["plan"]["split_value"] == 1
        assert "created_at" in body and "updated_at" in body

    def test_list_sorted_by_name(self, app_client, auth_headers):
        for name in ["Zebra", "Alpha", "Mid"]:
            app_client.post(
                "/api/v1/split-configs",
                headers=auth_headers,
                json={"name": name, "plan": _rolling_plan()},
            )
        listed = app_client.get("/api/v1/split-configs", headers=auth_headers)
        assert [c["name"] for c in listed.json()["configs"]] == ["Alpha", "Mid", "Zebra"]

    def test_get_missing_config_is_404(self, app_client, auth_headers):
        response = app_client.get(
            "/api/v1/split-configs/00000000-0000-0000-0000-000000000000", headers=auth_headers
        )
        assert response.status_code == 404

    def test_custom_plan_round_trips(self, app_client, auth_headers):
        create = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "Intervals", "plan": _custom_plan()},
        )
        assert create.status_code == 200
        plan = create.json()["plan"]
        assert plan["custom_splits"] == [[90.0, 4.0], [60.0, 6.0], [90.0, None]]
        assert plan["targets_as"] == "speed"
        assert plan["rolling_target_mps"] is None


class TestAuth:
    def test_list_requires_auth(self, app_client):
        response = app_client.get("/api/v1/split-configs")
        assert response.status_code == 401

    def test_create_requires_auth(self, app_client):
        response = app_client.post(
            "/api/v1/split-configs", json={"name": "x", "plan": _rolling_plan()}
        )
        assert response.status_code == 401


class TestPerUserIsolation:
    def test_user_cannot_see_another_users_config(self, app_client, auth_headers):
        create = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "Mine", "plan": _rolling_plan()},
        )
        config_id = create.json()["id"]

        other_headers = _other_user_headers(app_client)
        assert app_client.get("/api/v1/split-configs", headers=other_headers).json() == {
            "configs": []
        }
        assert (
            app_client.get(f"/api/v1/split-configs/{config_id}", headers=other_headers).status_code
            == 404
        )

    def test_user_cannot_edit_or_delete_another_users_config(self, app_client, auth_headers):
        create = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "Mine", "plan": _rolling_plan()},
        )
        config_id = create.json()["id"]
        other_headers = _other_user_headers(app_client)

        patch = app_client.patch(
            f"/api/v1/split-configs/{config_id}", headers=other_headers, json={"name": "Hijacked"}
        )
        assert patch.status_code == 404

        delete = app_client.delete(f"/api/v1/split-configs/{config_id}", headers=other_headers)
        assert delete.status_code == 404

        # Confirm it's untouched from the owner's perspective.
        got = app_client.get(f"/api/v1/split-configs/{config_id}", headers=auth_headers)
        assert got.json()["name"] == "Mine"

    def test_same_name_allowed_across_different_users(self, app_client, auth_headers):
        create = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "Same name", "plan": _rolling_plan()},
        )
        assert create.status_code == 200

        other_headers = _other_user_headers(app_client)
        create_other = app_client.post(
            "/api/v1/split-configs",
            headers=other_headers,
            json={"name": "Same name", "plan": _rolling_plan()},
        )
        assert create_other.status_code == 200


class TestNameCollision:
    def test_create_with_duplicate_name_is_409(self, app_client, auth_headers):
        app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "Dup", "plan": _rolling_plan()},
        )
        response = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "Dup", "plan": _rolling_plan(rolling_target_mps=3.0)},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "name_conflict"

    def test_create_with_overwrite_replaces_in_place(self, app_client, auth_headers):
        first = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "Dup", "plan": _rolling_plan()},
        )
        first_id = first.json()["id"]

        response = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={
                "name": "Dup",
                "plan": _rolling_plan(rolling_target_mps=3.5),
                "overwrite": True,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == first_id
        assert body["plan"]["rolling_target_mps"] == 3.5

        listed = app_client.get("/api/v1/split-configs", headers=auth_headers)
        assert len(listed.json()["configs"]) == 1

    def test_overwrite_with_no_existing_name_just_creates(self, app_client, auth_headers):
        response = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "New", "plan": _rolling_plan(), "overwrite": True},
        )
        assert response.status_code == 200

    def test_patch_rename_into_collision_is_409(self, app_client, auth_headers):
        app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "First", "plan": _rolling_plan()},
        )
        second = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "Second", "plan": _rolling_plan()},
        )
        second_id = second.json()["id"]

        response = app_client.patch(
            f"/api/v1/split-configs/{second_id}", headers=auth_headers, json={"name": "First"}
        )
        assert response.status_code == 409

    def test_patch_rename_to_own_current_name_is_a_noop_success(self, app_client, auth_headers):
        create = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "Same", "plan": _rolling_plan()},
        )
        config_id = create.json()["id"]
        response = app_client.patch(
            f"/api/v1/split-configs/{config_id}", headers=auth_headers, json={"name": "Same"}
        )
        assert response.status_code == 200


class TestPatchAndDelete:
    def test_patch_updates_plan_only(self, app_client, auth_headers):
        create = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "Edit me", "plan": _rolling_plan()},
        )
        config_id = create.json()["id"]

        response = app_client.patch(
            f"/api/v1/split-configs/{config_id}",
            headers=auth_headers,
            json={"plan": _custom_plan()},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Edit me"
        assert body["plan"]["custom_splits"] == [[90.0, 4.0], [60.0, 6.0], [90.0, None]]

    def test_patch_updates_name_only(self, app_client, auth_headers):
        create = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "Old name", "plan": _rolling_plan()},
        )
        config_id = create.json()["id"]

        response = app_client.patch(
            f"/api/v1/split-configs/{config_id}", headers=auth_headers, json={"name": "New name"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "New name"
        assert body["plan"]["rolling_target_mps"] == 2.5

    def test_patch_missing_config_is_404(self, app_client, auth_headers):
        response = app_client.patch(
            "/api/v1/split-configs/00000000-0000-0000-0000-000000000000",
            headers=auth_headers,
            json={"name": "x"},
        )
        assert response.status_code == 404

    def test_patch_rejects_invalid_plan(self, app_client, auth_headers):
        create = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "Valid", "plan": _rolling_plan()},
        )
        config_id = create.json()["id"]

        response = app_client.patch(
            f"/api/v1/split-configs/{config_id}",
            headers=auth_headers,
            json={"plan": _rolling_plan(split_value=0)},
        )
        assert response.status_code == 422

    def test_delete_removes_config(self, app_client, auth_headers):
        create = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "Delete me", "plan": _rolling_plan()},
        )
        config_id = create.json()["id"]

        response = app_client.delete(f"/api/v1/split-configs/{config_id}", headers=auth_headers)
        assert response.status_code == 204

        got = app_client.get(f"/api/v1/split-configs/{config_id}", headers=auth_headers)
        assert got.status_code == 404

    def test_delete_missing_config_is_404(self, app_client, auth_headers):
        response = app_client.delete(
            "/api/v1/split-configs/00000000-0000-0000-0000-000000000000", headers=auth_headers
        )
        assert response.status_code == 404


class TestValidation:
    def test_create_rejects_invalid_plan(self, app_client, auth_headers):
        response = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "Bad", "plan": _rolling_plan(split_value=-1)},
        )
        assert response.status_code == 422

    def test_create_rejects_blank_name(self, app_client, auth_headers):
        response = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "   ", "plan": _rolling_plan()},
        )
        assert response.status_code == 422

    def test_create_rejects_both_rolling_and_custom(self, app_client, auth_headers):
        response = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={
                "name": "Bad",
                "plan": _rolling_plan(custom_splits=[[400.0, None]]),
            },
        )
        assert response.status_code == 422

    def test_create_rejects_too_many_custom_splits(self, app_client, auth_headers):
        too_many = [[100.0, None] for _ in range(51)]
        response = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={
                "name": "Bad",
                "plan": _rolling_plan(rolling_target_mps=None, custom_splits=too_many),
            },
        )
        assert response.status_code == 422

    # Unknown fields are ignored, not rejected, so a newer app can't be broken
    # by this server (docs/VERSIONING.md §5) — but they must never be stored.
    def test_create_ignores_unknown_fields_in_plan(self, app_client, auth_headers):
        plan = _rolling_plan()
        plan["unexpected"] = True
        response = app_client.post(
            "/api/v1/split-configs", headers=auth_headers, json={"name": "Extra", "plan": plan}
        )
        assert response.status_code == 200
        assert "unexpected" not in response.json()["plan"]

    def test_create_ignores_unknown_top_level_fields(self, app_client, auth_headers):
        response = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "Extra", "plan": _rolling_plan(), "unexpected": True},
        )
        assert response.status_code == 200
        assert "unexpected" not in response.json()


class TestRateLimiting:
    """A code-review finding (2026-09-22): delete_split_config never called
    _require_rate_limit, unlike create/patch on the same router, despite
    docs/SPLIT-CONFIGS-PLAN.md §3 explicitly saying POST/PATCH/DELETE should
    all be covered. Fixed — this locks the fix in specifically for DELETE
    (create/patch's own rate limiting was already covered before this
    finding, by _require_rate_limit being called from both)."""

    def test_delete_itself_is_rate_limited_after_repeated_deletes(self, app_client, auth_headers):
        # Inserted directly rather than via POST, since POST shares
        # account_action_rate_limiter's budget with DELETE and would trip
        # it itself before this test ever exercises DELETE's own limit.
        from app.auth.rate_limit import account_action_rate_limiter
        from app.db import get_session_factory
        from app.models.split_config import SplitConfig
        from app.repositories.split_configs import SqlAlchemySplitConfigRepository
        from app.repositories.users import SqlAlchemyUserRepository

        with get_session_factory()() as session:
            user = SqlAlchemyUserRepository(session).get_by_email("admin@example.com")
            assert user is not None
            repo = SqlAlchemySplitConfigRepository(session)
            now = datetime.now(UTC)
            config_ids = []
            for i in range(6):
                config = SplitConfig(
                    user_id=user.id,
                    name=f"Config {i}",
                    plan=_rolling_plan(),
                    created_at=now,
                    updated_at=now,
                )
                repo.add(config)
                session.flush()
                config_ids.append(config.id)
            session.commit()

        account_action_rate_limiter.reset()

        for config_id in config_ids[:5]:
            response = app_client.delete(f"/api/v1/split-configs/{config_id}", headers=auth_headers)
            assert response.status_code == 204

        response = app_client.delete(f"/api/v1/split-configs/{config_ids[5]}", headers=auth_headers)
        assert response.status_code == 429
