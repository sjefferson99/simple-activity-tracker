"""Split library API (issue #143, docs/SPLIT-LIBRARY-PLAN.md): sources,
folders, sync, read-only templates in /split-configs, folders on own configs,
and import/export. Repos are served by a stub fetcher."""

import json

from app.split_library import library
from tests.conftest import OTHER_USER_PASSWORD, create_user
from tests.split_library_helpers import (
    C25K_W1,
    DEFAULT_REPO,
    INTERVAL,
    config_file,
    default_repo_files,
    install_stub,
    plan_time,
)

ROLLING = {
    "split_type": "distance_km",
    "split_value": 1,
    "rolling_target_mps": 2.5,
    "custom_splits": [],
    "targets_as": "pace",
}


def _sources(client, headers):
    response = client.get("/api/v1/split-sources", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _default_source(client, headers):
    return next(s for s in _sources(client, headers)["sources"] if s["is_default"])


def _sync(client, headers, source_id):
    response = client.post(f"/api/v1/split-sources/{source_id}/sync", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _configs(client, headers):
    response = client.get("/api/v1/split-configs", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["configs"]


def _synced_default(app_client, auth_headers, monkeypatch):
    stub = install_stub(monkeypatch)
    stub.serve("example/split-templates", default_repo_files())
    source = _default_source(app_client, auth_headers)
    result = _sync(app_client, auth_headers, source["id"])
    return stub, source, result


class TestDefaultSourceAndSync:
    def test_no_default_repo_means_no_sources(self, app_client, auth_headers):
        body = _sources(app_client, auth_headers)
        assert body["sources"] == []
        assert body["can_add"] is True

    def test_default_source_is_created_and_synced(self, app_client, auth_headers, monkeypatch):
        stub, source, result = _synced_default(app_client, auth_headers, monkeypatch)
        assert source["url"] == DEFAULT_REPO
        assert source["ref"] == "main"
        assert source["path"] == "splits"
        assert result["ok"] is True
        assert result["added"] == 3
        synced = result["source"]
        assert synced["last_commit"] == "abc1234def"
        folders = {f["folder"]: f for f in synced["folders"]}
        assert folders["couch-to-5k"]["name"] == "Couch to 5K"
        assert folders["couch-to-5k"]["description"] == "Nine weeks to 5K"
        assert folders["couch-to-5k"]["template_count"] == 2
        assert folders["intervals"]["name"] == "intervals"
        assert all(f["enabled"] for f in folders.values())
        assert stub.requests[0][0] == (
            "https://api.github.com/repos/example/split-templates/tarball/main"
        )

    def test_templates_listed_read_only_with_folder(self, app_client, auth_headers, monkeypatch):
        _synced_default(app_client, auth_headers, monkeypatch)
        configs = {c["name"]: c for c in _configs(app_client, auth_headers)}
        week1 = configs["C25K week 1 run 1"]
        assert week1["read_only"] is True
        assert week1["uid"] == C25K_W1
        assert week1["folder"] == "couch-to-5k"
        assert week1["folder_name"] == "Couch to 5K"
        assert week1["source"]["name"] == library.DEFAULT_SOURCE_NAME
        assert week1["plan"]["custom_splits"] == [[300.0, 1.667], [60.0, 2.222]]

    def test_list_triggers_first_sync_in_background(self, app_client, auth_headers, monkeypatch):
        stub = install_stub(monkeypatch)
        stub.serve("example/split-templates", default_repo_files())
        # TestClient runs background tasks before returning, so the first
        # list subscribes and syncs, and the next one sees the templates.
        assert _configs(app_client, auth_headers) == []
        assert len(_configs(app_client, auth_headers)) == 3
        assert len(stub.requests) == 1  # not due again yet

    def test_resync_updates_moves_and_removes(self, app_client, auth_headers, monkeypatch):
        stub, source, _ = _synced_default(app_client, auth_headers, monkeypatch)
        week1_id = next(c["id"] for c in _configs(app_client, auth_headers) if c["uid"] == C25K_W1)
        files = default_repo_files()
        del files["splits/intervals/fartlek.json"]
        # Renamed and moved, same uid: updated in place.
        del files["splits/couch-to-5k/week-1-run-1.json"]
        files["splits/c25k-v2/w1r1.json"] = config_file(
            "C25K W1R1", C25K_W1, custom_splits=[[600, 1.667]]
        )
        stub.serve("example/split-templates", files)
        result = _sync(app_client, auth_headers, source["id"])
        assert (result["added"], result["updated"], result["removed"]) == (0, 1, 1)
        configs = {c["uid"]: c for c in _configs(app_client, auth_headers)}
        assert INTERVAL not in configs
        moved = configs[C25K_W1]
        assert moved["id"] == week1_id
        assert moved["name"] == "C25K W1R1"
        assert moved["folder"] == "c25k-v2"
        folders = {f["folder"] for f in result["source"]["folders"]}
        assert folders == {"couch-to-5k", "c25k-v2"}

    def test_invalid_files_are_warnings_not_failures(self, app_client, auth_headers, monkeypatch):
        stub = install_stub(monkeypatch)
        files = default_repo_files()
        files["splits/bad/not-json.json"] = b"{nope"
        files["splits/bad/wrong-format.json"] = b'{"format": "other"}'
        files["splits/bad/bad-plan.json"] = config_file("Bad", custom_splits=[[-1, None]])
        files["splits/dupe.json"] = config_file("Dupe", C25K_W1)
        stub.serve("example/split-templates", files)
        result = _sync(app_client, auth_headers, _default_source(app_client, auth_headers)["id"])
        assert result["ok"] is True
        assert result["added"] == 3
        warnings = result["source"]["warnings"]
        assert len(warnings) == 4
        assert any(w.startswith("bad/not-json.json") for w in warnings)
        assert any("same uid" in w for w in warnings)

    def test_file_without_uid_gets_a_stable_one(self, app_client, auth_headers, monkeypatch):
        stub = install_stub(monkeypatch)
        stub.serve("example/split-templates", {"splits/x/a.json": config_file("A")})
        source = _default_source(app_client, auth_headers)
        _sync(app_client, auth_headers, source["id"])
        first = _configs(app_client, auth_headers)[0]
        result = _sync(app_client, auth_headers, source["id"])
        assert (result["added"], result["updated"], result["removed"]) == (0, 0, 0)
        assert _configs(app_client, auth_headers)[0]["id"] == first["id"]
        # Top-level files land in a "General" folder.
        stub.serve("example/split-templates", {"splits/a.json": config_file("A")})
        result = _sync(app_client, auth_headers, source["id"])
        assert [f["name"] for f in result["source"]["folders"]] == ["General"]

    def test_failed_sync_keeps_templates_and_reports(self, app_client, auth_headers, monkeypatch):
        stub, source, _ = _synced_default(app_client, auth_headers, monkeypatch)
        stub.fail("example/split-templates", "The repo host answered 500")
        result = _sync(app_client, auth_headers, source["id"])
        assert result["ok"] is False
        assert result["error"] == "The repo host answered 500"
        assert result["source"]["last_error"] == "The repo host answered 500"
        assert len(_configs(app_client, auth_headers)) == 3

    def test_default_repo_turned_off_hides_default_source(
        self, app_client, auth_headers, monkeypatch
    ):
        from app.config import get_settings

        _synced_default(app_client, auth_headers, monkeypatch)
        monkeypatch.setenv("SR_SPLIT_LIBRARY_DEFAULT_REPO", "")
        get_settings.cache_clear()
        assert _sources(app_client, auth_headers)["sources"] == []
        assert _configs(app_client, auth_headers) == []


class TestVisibility:
    def test_folder_toggle_hides_templates(self, app_client, auth_headers, monkeypatch):
        _, source, result = _synced_default(app_client, auth_headers, monkeypatch)
        folder = next(f for f in result["source"]["folders"] if f["folder"] == "couch-to-5k")
        response = app_client.patch(
            f"/api/v1/split-sources/{source['id']}/folders/{folder['id']}",
            headers=auth_headers,
            json={"enabled": False},
        )
        assert response.status_code == 200
        assert [c["name"] for c in _configs(app_client, auth_headers)] == ["Fartlek"]
        app_client.patch(
            f"/api/v1/split-sources/{source['id']}/folders/{folder['id']}",
            headers=auth_headers,
            json={"enabled": True},
        )
        assert len(_configs(app_client, auth_headers)) == 3

    def test_folder_state_survives_resync(self, app_client, auth_headers, monkeypatch):
        _, source, result = _synced_default(app_client, auth_headers, monkeypatch)
        folder = next(f for f in result["source"]["folders"] if f["folder"] == "intervals")
        app_client.patch(
            f"/api/v1/split-sources/{source['id']}/folders/{folder['id']}",
            headers=auth_headers,
            json={"enabled": False},
        )
        _sync(app_client, auth_headers, source["id"])
        assert "Fartlek" not in [c["name"] for c in _configs(app_client, auth_headers)]

    def test_source_switch_hides_all_its_templates(self, app_client, auth_headers, monkeypatch):
        _, source, _ = _synced_default(app_client, auth_headers, monkeypatch)
        response = app_client.patch(
            f"/api/v1/split-sources/{source['id']}", headers=auth_headers, json={"enabled": False}
        )
        assert response.status_code == 200
        assert response.json()["enabled"] is False
        assert _configs(app_client, auth_headers) == []

    def test_unknown_folder_is_404(self, app_client, auth_headers, monkeypatch):
        _, source, _ = _synced_default(app_client, auth_headers, monkeypatch)
        response = app_client.patch(
            f"/api/v1/split-sources/{source['id']}/folders/nope",
            headers=auth_headers,
            json={"enabled": False},
        )
        assert response.status_code == 404

    def test_other_users_cannot_see_or_touch(self, app_client, auth_headers, monkeypatch):
        _, source, result = _synced_default(app_client, auth_headers, monkeypatch)
        create_user("other@example.com", "Other")
        login = app_client.post(
            "/api/v1/auth/login",
            json={
                "email": "other@example.com",
                "password": OTHER_USER_PASSWORD,
                "device_name": "t",
            },
        )
        other = {"Authorization": f"Bearer {login.json()['token']}"}
        folder_id = result["source"]["folders"][0]["id"]
        assert (
            app_client.patch(
                f"/api/v1/split-sources/{source['id']}/folders/{folder_id}",
                headers=other,
                json={"enabled": False},
            ).status_code
            == 404
        )
        assert (
            app_client.post(f"/api/v1/split-sources/{source['id']}/sync", headers=other).status_code
            == 404
        )
        template_id = _configs(app_client, auth_headers)[0]["id"]
        assert (
            app_client.get(f"/api/v1/split-configs/{template_id}", headers=other).status_code == 404
        )


class TestReadOnlyTemplates:
    def test_patch_and_delete_are_refused(self, app_client, auth_headers, monkeypatch):
        _synced_default(app_client, auth_headers, monkeypatch)
        template = _configs(app_client, auth_headers)[0]
        response = app_client.patch(
            f"/api/v1/split-configs/{template['id']}", headers=auth_headers, json={"name": "Mine"}
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "read_only"
        response = app_client.delete(
            f"/api/v1/split-configs/{template['id']}", headers=auth_headers
        )
        assert response.status_code == 403

    def test_template_name_is_free_for_own_config(self, app_client, auth_headers, monkeypatch):
        """An old app's save-as with a template's name (even with overwrite)
        creates the user's own config and leaves the template alone."""
        _synced_default(app_client, auth_headers, monkeypatch)
        for overwrite in (False, True):
            response = app_client.post(
                "/api/v1/split-configs",
                headers=auth_headers,
                json={"name": "Fartlek", "plan": ROLLING, "overwrite": overwrite},
            )
            assert response.status_code == 200, response.text
        fartleks = [c for c in _configs(app_client, auth_headers) if c["name"] == "Fartlek"]
        assert sorted(c["read_only"] for c in fartleks) == [False, True]
        template = next(c for c in fartleks if c["read_only"])
        assert template["plan"]["split_type"] == "time_min"


class TestOwnFolders:
    def test_create_with_folder_and_patch_it(self, app_client, auth_headers):
        response = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "Hills", "plan": ROLLING, "folder": "  Club   sessions "},
        )
        assert response.status_code == 200
        created = response.json()
        assert created["folder"] == "Club sessions"
        assert created["folder_name"] == "Club sessions"
        assert created["read_only"] is False
        assert created["source"] is None
        assert created["uid"]
        response = app_client.patch(
            f"/api/v1/split-configs/{created['id']}", headers=auth_headers, json={"folder": ""}
        )
        assert response.json()["folder"] is None

    def test_overwrite_keeps_folder_unless_given(self, app_client, auth_headers):
        app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "Hills", "plan": ROLLING, "folder": "Club"},
        )
        response = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "Hills", "plan": ROLLING, "overwrite": True},
        )
        assert response.json()["folder"] == "Club"
        response = app_client.post(
            "/api/v1/split-configs",
            headers=auth_headers,
            json={"name": "Hills", "plan": ROLLING, "overwrite": True, "folder": "Other"},
        )
        assert response.json()["folder"] == "Other"


class TestSourcesCrud:
    def test_add_private_gitea_source_syncs_with_token(self, app_client, auth_headers, monkeypatch):
        stub = install_stub(monkeypatch, default_repo=None)
        stub.serve("git.example.org", {"plans/mine/a.json": config_file("Mine A")})
        response = app_client.post(
            "/api/v1/split-sources",
            headers=auth_headers,
            json={
                "url": "https://git.example.org/me/plans.git",
                "path": "/plans/",
                "token": "secret-token",
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["ok"] is True
        source = body["source"]
        assert source["host_kind"] == "gitea"
        assert source["name"] == "me/plans"
        assert source["path"] == "plans"
        assert source["has_token"] is True
        assert "secret-token" not in response.text
        assert stub.requests[0][1]["Authorization"] == "token secret-token"
        listed = app_client.get("/api/v1/split-sources", headers=auth_headers).text
        assert "secret-token" not in listed
        assert [c["name"] for c in _configs(app_client, auth_headers)] == ["Mine A"]

    def test_failed_first_sync_keeps_the_subscription(self, app_client, auth_headers, monkeypatch):
        install_stub(monkeypatch, default_repo=None)
        response = app_client.post(
            "/api/v1/split-sources",
            headers=auth_headers,
            json={"url": "https://github.com/me/private"},
        )
        assert response.status_code == 201
        assert response.json()["ok"] is False
        assert "404" in response.json()["source"]["last_error"]

    def test_rejects_bad_urls_and_duplicates(self, app_client, auth_headers, monkeypatch):
        stub = install_stub(monkeypatch, default_repo=None)
        stub.serve("o/r", {})
        for url in ("http://github.com/o/r", "https://github.com/o", "ftp://x/y/z"):
            response = app_client.post(
                "/api/v1/split-sources", headers=auth_headers, json={"url": url}
            )
            assert response.status_code == 422, url
        assert (
            app_client.post(
                "/api/v1/split-sources",
                headers=auth_headers,
                json={"url": "https://github.com/o/r"},
            ).status_code
            == 201
        )
        response = app_client.post(
            "/api/v1/split-sources", headers=auth_headers, json={"url": "https://github.com/o/r/"}
        )
        assert response.status_code == 422
        assert "already" in response.json()["error"]["message"]

    def test_user_repos_can_be_disallowed(self, app_client, auth_headers, monkeypatch):
        from app.config import get_settings

        install_stub(monkeypatch, default_repo=None)
        monkeypatch.setenv("SR_SPLIT_SOURCES_ALLOW_USER_REPOS", "false")
        get_settings.cache_clear()
        assert _sources(app_client, auth_headers)["can_add"] is False
        response = app_client.post(
            "/api/v1/split-sources", headers=auth_headers, json={"url": "https://github.com/o/r"}
        )
        assert response.status_code == 422

    def test_turning_user_repos_off_stops_syncing_them(self, app_client, auth_headers, monkeypatch):
        from app.config import get_settings

        stub = install_stub(monkeypatch)
        stub.serve("example/split-templates", default_repo_files())
        stub.serve("o/r", {"splits/a.json": config_file("From R")})
        source = app_client.post(
            "/api/v1/split-sources", headers=auth_headers, json={"url": "https://github.com/o/r"}
        ).json()["source"]
        monkeypatch.setenv("SR_SPLIT_SOURCES_ALLOW_USER_REPOS", "false")
        get_settings.cache_clear()
        requests_before = len(stub.requests)
        result = _sync(app_client, auth_headers, source["id"])
        assert result["ok"] is False
        assert "default split repo" in result["error"]
        assert len(stub.requests) == requests_before
        # The default repo still syncs.
        default = _default_source(app_client, auth_headers)
        assert _sync(app_client, auth_headers, default["id"])["ok"] is True

    def test_edit_token_and_location(self, app_client, auth_headers, monkeypatch):
        stub = install_stub(monkeypatch, default_repo=None)
        stub.serve("o/r", {})
        source = app_client.post(
            "/api/v1/split-sources",
            headers=auth_headers,
            json={"url": "https://github.com/o/r", "token": "one"},
        ).json()["source"]
        response = app_client.patch(
            f"/api/v1/split-sources/{source['id']}",
            headers=auth_headers,
            json={"ref": "v2", "path": "x", "name": "Renamed", "clear_token": True},
        )
        assert response.status_code == 200
        body = response.json()
        assert (body["ref"], body["path"], body["name"], body["has_token"]) == (
            "v2",
            "x",
            "Renamed",
            False,
        )
        response = app_client.patch(
            f"/api/v1/split-sources/{source['id']}", headers=auth_headers, json={"ref": "a b"}
        )
        assert response.status_code == 422

    def test_delete_source_removes_its_templates(self, app_client, auth_headers, monkeypatch):
        stub = install_stub(monkeypatch, default_repo=None)
        stub.serve("o/r", {"splits/a.json": config_file("From R")})
        source = app_client.post(
            "/api/v1/split-sources", headers=auth_headers, json={"url": "https://github.com/o/r"}
        ).json()["source"]
        assert len(_configs(app_client, auth_headers)) == 1
        response = app_client.delete(f"/api/v1/split-sources/{source['id']}", headers=auth_headers)
        assert response.status_code == 204
        assert _configs(app_client, auth_headers) == []
        assert _sources(app_client, auth_headers)["sources"] == []

    def test_default_source_is_switch_only(self, app_client, auth_headers, monkeypatch):
        _, source, _ = _synced_default(app_client, auth_headers, monkeypatch)
        assert (
            app_client.delete(
                f"/api/v1/split-sources/{source['id']}", headers=auth_headers
            ).status_code
            == 403
        )
        assert (
            app_client.patch(
                f"/api/v1/split-sources/{source['id']}", headers=auth_headers, json={"ref": "dev"}
            ).status_code
            == 403
        )

    def test_fetches_are_rate_limited(self, app_client, auth_headers, monkeypatch):
        _, source, _ = _synced_default(app_client, auth_headers, monkeypatch)
        statuses = [
            app_client.post(
                f"/api/v1/split-sources/{source['id']}/sync", headers=auth_headers
            ).status_code
            for _ in range(12)
        ]
        assert 429 in statuses


class TestImportExport:
    def _create(self, client, headers, name, folder=None):
        body = {"name": name, "plan": ROLLING}
        if folder:
            body["folder"] = folder
        response = client.post("/api/v1/split-configs", headers=headers, json=body)
        assert response.status_code == 200, response.text
        return response.json()

    def test_export_all_then_import_elsewhere(self, app_client, auth_headers):
        self._create(app_client, auth_headers, "Hills", "Club")
        self._create(app_client, auth_headers, "Easy")
        response = app_client.get("/api/v1/split-configs/export", headers=auth_headers)
        assert response.status_code == 200
        assert 'filename="split-configs.json"' in response.headers["content-disposition"]
        document = response.json()
        assert document["format"] == "sat-split-configs"
        assert {c["name"]: c["folder"] for c in document["configs"]} == {
            "Hills": "Club",
            "Easy": None,
        }

        create_user("other@example.com", "Other")
        login = app_client.post(
            "/api/v1/auth/login",
            json={
                "email": "other@example.com",
                "password": OTHER_USER_PASSWORD,
                "device_name": "t",
            },
        )
        other = {"Authorization": f"Bearer {login.json()['token']}"}
        response = app_client.post("/api/v1/split-configs/import", headers=other, json=document)
        assert response.status_code == 200, response.text
        assert response.json() == {"created": 2, "updated": 0, "renamed": [], "errors": []}
        imported = {c["name"]: c for c in _configs(app_client, other)}
        assert imported["Hills"]["folder"] == "Club"
        originals = {c["name"]: c["uid"] for c in document["configs"]}
        assert imported["Hills"]["uid"] == originals["Hills"]

    def test_reimport_replaces_by_uid_and_renames_new_clashes(self, app_client, auth_headers):
        hills = self._create(app_client, auth_headers, "Hills")
        document = app_client.get(
            f"/api/v1/split-configs/export?id={hills['id']}", headers=auth_headers
        ).json()
        assert document["format"] == "sat-split-config"
        document["plan"] = plan_time((120, 3.0))
        response = app_client.post(
            "/api/v1/split-configs/import", headers=auth_headers, json=document
        )
        assert response.json()["updated"] == 1
        assert _configs(app_client, auth_headers)[0]["plan"]["custom_splits"] == [[120.0, 3.0]]
        # A different config with the same name is added as "Hills (2)".
        del document["uid"]
        response = app_client.post(
            "/api/v1/split-configs/import", headers=auth_headers, json=document
        )
        assert response.json()["created"] == 1
        assert response.json()["renamed"] == ["Hills → Hills (2)"]

    def test_export_folder_and_template(self, app_client, auth_headers, monkeypatch):
        _synced_default(app_client, auth_headers, monkeypatch)
        self._create(app_client, auth_headers, "Hills", "Club")
        self._create(app_client, auth_headers, "Easy")
        document = app_client.get(
            "/api/v1/split-configs/export?folder=Club", headers=auth_headers
        ).json()
        assert [c["name"] for c in document["configs"]] == ["Hills"]
        template = next(c for c in _configs(app_client, auth_headers) if c["uid"] == C25K_W1)
        response = app_client.get(
            f"/api/v1/split-configs/export?id={template['id']}", headers=auth_headers
        )
        assert response.json()["uid"] == C25K_W1
        assert 'filename="C25K-week-1-run-1.json"' in response.headers["content-disposition"]
        assert (
            app_client.get(
                "/api/v1/split-configs/export?id=missing", headers=auth_headers
            ).status_code
            == 404
        )

    def test_export_refuses_too_many_ids(self, app_client, auth_headers):
        query = "&".join(f"id=x{i}" for i in range(501))
        response = app_client.get(f"/api/v1/split-configs/export?{query}", headers=auth_headers)
        assert response.status_code == 422

    def test_import_reports_bad_entries_and_rejects_bad_files(self, app_client, auth_headers):
        bundle = {
            "format": "sat-split-configs",
            "version": 1,
            "configs": [
                {"name": "Good", "plan": ROLLING},
                {"name": "Bad", "plan": {**ROLLING, "split_value": 0}},
                {"name": "Bad uid", "uid": "nope", "plan": ROLLING},
            ],
        }
        response = app_client.post(
            "/api/v1/split-configs/import", headers=auth_headers, json=bundle
        )
        assert response.status_code == 200
        body = response.json()
        assert body["created"] == 1
        assert len(body["errors"]) == 2
        response = app_client.post(
            "/api/v1/split-configs/import", headers=auth_headers, json={"format": "other"}
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_file"

    def test_exported_file_matches_repo_file_format(self, app_client, auth_headers, monkeypatch):
        """A single-config export can be dropped straight into a split repo."""
        hills = self._create(app_client, auth_headers, "Hills")
        document = app_client.get(
            f"/api/v1/split-configs/export?id={hills['id']}", headers=auth_headers
        ).json()
        stub = install_stub(monkeypatch, default_repo=None)
        stub.serve("o/r", {"splits/club/hills.json": json.dumps(document).encode()})
        result = app_client.post(
            "/api/v1/split-sources", headers=auth_headers, json={"url": "https://github.com/o/r"}
        ).json()
        assert result["added"] == 1


class TestUserDeletion:
    def test_deleting_a_user_removes_their_library(self, app_client, auth_headers, monkeypatch):
        install_stub(monkeypatch).serve("example/split-templates", default_repo_files())
        user_id = create_user("other@example.com", "Other")
        login = app_client.post(
            "/api/v1/auth/login",
            json={
                "email": "other@example.com",
                "password": OTHER_USER_PASSWORD,
                "device_name": "t",
            },
        )
        other = {"Authorization": f"Bearer {login.json()['token']}"}
        _sync(app_client, other, _default_source(app_client, other)["id"])
        app_client.post(
            "/api/v1/split-configs", headers=other, json={"name": "Mine", "plan": ROLLING}
        )
        response = app_client.delete(f"/api/v1/admin/users/{user_id}", headers=auth_headers)
        assert response.status_code in (200, 204), response.text
