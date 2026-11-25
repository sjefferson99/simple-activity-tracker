"""Web pages for the split library (issue #143): the splits page grouped by
folder with read-only templates, the template view and Copy, the folder
field, and the library page (repos, folder switches, import/export)."""

import json
import re

from tests.split_library_helpers import (
    C25K_W1,
    HTMX,
    config_file,
    default_repo_files,
    install_stub,
)


def _login(client):
    response = client.post(
        "/login",
        headers=HTMX,
        data={"email": "admin@example.com", "password": "admin-password-123"},
    )
    assert response.status_code == 200
    return client


def _with_default_repo(app_client, monkeypatch):
    stub = install_stub(monkeypatch)
    stub.serve("example/split-templates", default_repo_files())
    return stub


def _template_id(client, auth_headers, uid=C25K_W1):
    configs = client.get("/api/v1/split-configs", headers=auth_headers).json()["configs"]
    return next(c["id"] for c in configs if c["uid"] == uid)


def _create(client, **fields):
    data = {
        "config_id": "",
        "name": "Hills",
        "folder": "",
        "split_type": "distance_km",
        "split_value": "1",
        "targets_as": "pace",
        "plan_kind": "rolling",
        "rolling_target": "5:00",
    }
    data.update(fields)
    return client.post("/split-configs", headers=HTMX, data=data)


class TestSplitsPage:
    def test_first_visit_syncs_default_repo_and_groups(self, app_client, auth_headers, monkeypatch):
        stub = _with_default_repo(app_client, monkeypatch)
        client = _login(app_client)
        assert _create(client, name="Hills", folder="Club").status_code == 200
        assert _create(client, name="Easy").status_code == 200
        page = client.get("/split-configs").text
        assert len(stub.requests) == 1
        headings = re.findall(r"<h2>(.*?)</h2>", page)
        assert headings == ["My splits", "Club", "Couch to 5K", "intervals"]
        assert "C25K week 1 run 1" in page
        assert "Template" in page
        assert "from Simple Activity Tracker templates" in page
        # Templates offer View/Copy/Export, never Edit/Delete.
        template_id = _template_id(client, auth_headers)
        assert f"/split-configs/{template_id}/duplicate" in page
        assert f'hx-delete="/split-configs/{template_id}"' not in page
        # Natural order inside a group.
        assert page.index("C25K week 1 run 1") < page.index("C25K week 2 run 1")

    def test_hidden_folder_is_not_on_the_page(self, app_client, auth_headers, monkeypatch):
        _with_default_repo(app_client, monkeypatch)
        client = _login(app_client)
        client.get("/split-configs")
        sources = client.get("/api/v1/split-sources", headers=auth_headers).json()["sources"]
        folder = next(f for f in sources[0]["folders"] if f["folder"] == "couch-to-5k")
        response = client.patch(
            f"/split-configs/library/folders/{folder['id']}",
            headers=HTMX,
            data={"enabled": "false"},
        )
        assert response.status_code == 200
        page = client.get("/split-configs").text
        assert "C25K week 1 run 1" not in page
        assert "Fartlek" in page

    def test_empty_page_points_at_library(self, app_client, auth_headers):
        page = _login(app_client).get("/split-configs").text
        assert "/split-configs/library" in page
        assert "No saved split configs yet" in page


class TestTemplates:
    def test_view_is_read_only(self, app_client, auth_headers, monkeypatch):
        _with_default_repo(app_client, monkeypatch)
        client = _login(app_client)
        client.get("/split-configs")
        template_id = _template_id(client, auth_headers)
        page = client.get(f"/split-configs/{template_id}/edit").text
        assert "<fieldset disabled" in page
        assert ">Save</button>" not in page
        assert f'href="/split-configs/{template_id}/duplicate"' in page
        assert 'value="Couch to 5K"' in page

    def test_copy_keeps_free_name_and_folder(self, app_client, auth_headers, monkeypatch):
        _with_default_repo(app_client, monkeypatch)
        client = _login(app_client)
        client.get("/split-configs")
        template_id = _template_id(client, auth_headers)
        page = client.get(f"/split-configs/{template_id}/duplicate").text
        assert 'value="C25K week 1 run 1"' in page
        # Not one of the user's folders yet, so it starts as a new one.
        assert '<option value="__new__" selected>' in page
        assert 'name="folder_new" value="Couch to 5K"' in page
        assert "<fieldset disabled" not in page
        assert 'name="config_id" value=""' in page

    def test_web_save_and_delete_of_template_are_refused(
        self, app_client, auth_headers, monkeypatch
    ):
        _with_default_repo(app_client, monkeypatch)
        client = _login(app_client)
        client.get("/split-configs")
        template_id = _template_id(client, auth_headers)
        assert _create(client, config_id=template_id).status_code == 403
        assert client.delete(f"/split-configs/{template_id}", headers=HTMX).status_code == 403


class TestFolderField:
    def test_folder_saved_and_offered(self, app_client, auth_headers):
        client = _login(app_client)
        assert _create(client, name="Hills", folder=" Club ").status_code == 200
        configs = client.get("/api/v1/split-configs", headers=auth_headers).json()["configs"]
        assert configs[0]["folder"] == "Club"
        page = client.get("/split-configs/new").text
        assert '<option value="Club" >Club</option>' in page
        assert "<datalist" not in page
        edit = client.get(f"/split-configs/{configs[0]['id']}/edit").text
        assert '<option value="Club" selected>Club</option>' in edit
        assert 'name="folder_new"' not in edit

    def test_folder_survives_row_rerender(self, app_client, auth_headers):
        client = _login(app_client)
        response = client.post(
            "/split-configs/custom-rows",
            headers=HTMX,
            data={"folder": "Club", "plan_kind": "custom", "row_action": "add"},
        )
        assert 'name="folder_new" value="Club"' in response.text

    def test_dropdown_new_folder_and_existing(self, app_client, auth_headers):
        client = _login(app_client)
        # Choosing "New folder…" re-renders with a name box.
        response = client.post(
            "/split-configs/custom-rows",
            headers=HTMX,
            data={"folder_choice": "__new__", "folder_new": "", "plan_kind": "rolling"},
        )
        assert '<option value="__new__" selected>' in response.text
        assert 'name="folder_new" value=""' in response.text
        # Saving with a new folder name, then into that existing folder.
        assert (
            _create(client, name="A", folder_choice="__new__", folder_new="Track").status_code
            == 200
        )
        assert (
            _create(client, name="B", folder_choice="Track", folder_new="ignored").status_code
            == 200
        )
        assert _create(client, name="C", folder_choice="", folder_new="ignored").status_code == 200
        configs = client.get("/api/v1/split-configs", headers=auth_headers).json()["configs"]
        assert {c["name"]: c["folder"] for c in configs} == {"A": "Track", "B": "Track", "C": None}


class TestLibraryPage:
    def test_renders_sources_and_folders(self, app_client, auth_headers, monkeypatch):
        _with_default_repo(app_client, monkeypatch)
        client = _login(app_client)
        client.get("/split-configs")
        page = client.get("/split-configs/library").text
        assert "Simple Activity Tracker templates" in page
        assert "Couch to 5K" in page
        assert "Nine weeks to 5K" in page
        assert "2 splits" in page
        assert "Add a split repo" in page
        # The default repo can't be removed or edited.
        assert "Remove" not in page.split("Add a split repo")[0]

    def test_add_sync_and_remove_a_repo(self, app_client, auth_headers, monkeypatch):
        stub = install_stub(monkeypatch, default_repo=None)
        stub.serve("o/club", {"splits/club/a.json": config_file("Club A")})
        client = _login(app_client)
        response = client.post(
            "/split-configs/library/sources",
            headers=HTMX,
            data={
                "url": "https://github.com/o/club",
                "ref": "main",
                "path": "splits",
                "token": "t0k",
            },
        )
        assert response.status_code == 200
        assert "o/club synced: 1 added." in response.text
        assert "private (token set)" in response.text
        assert "t0k" not in response.text
        source_id = re.search(r"/split-configs/library/sources/([0-9a-f-]{36})/sync", response.text)
        assert source_id
        response = client.post(
            f"/split-configs/library/sources/{source_id.group(1)}/sync", headers=HTMX
        )
        assert "no changes" in response.text
        response = client.delete(
            f"/split-configs/library/sources/{source_id.group(1)}", headers=HTMX
        )
        assert "Removed o/club." in response.text

    def test_add_error_keeps_form(self, app_client, auth_headers, monkeypatch):
        install_stub(monkeypatch, default_repo=None)
        client = _login(app_client)
        response = client.post(
            "/split-configs/library/sources",
            headers=HTMX,
            data={"url": "http://github.com/o/r", "ref": "dev", "path": "splits"},
        )
        assert response.status_code == 400
        assert "must start with https://" in response.text
        assert 'value="dev"' in response.text

    def test_mutations_need_htmx_header(self, app_client, auth_headers):
        client = _login(app_client)
        assert client.post("/split-configs/library/sources", data={"url": "x"}).status_code == 403
        assert client.patch("/split-configs/library/folders/x", data={}).status_code == 403
        assert (
            client.post("/split-configs/import", files={"file": ("a.json", b"{}")}).status_code
            == 403
        )

    def test_signed_out_redirects(self, app_client):
        response = app_client.get("/split-configs/library", follow_redirects=False)
        assert response.status_code == 303


class TestWebImportExport:
    def test_export_then_import_file(self, app_client, auth_headers):
        client = _login(app_client)
        _create(client, name="Hills", folder="Club")
        response = client.get("/split-configs/export")
        assert response.status_code == 200
        assert "attachment" in response.headers["content-disposition"]
        document = response.json()
        document["configs"][0]["uid"] = None
        response = client.post(
            "/split-configs/import",
            headers=HTMX,
            files={"file": ("splits.json", json.dumps(document).encode(), "application/json")},
        )
        assert response.status_code == 200
        assert "1 new" in response.text
        assert "Hills → Hills (2)" in response.text

    def test_import_rejects_non_split_file(self, app_client, auth_headers):
        client = _login(app_client)
        response = client.post(
            "/split-configs/import",
            headers=HTMX,
            files={"file": ("x.json", b"[1, 2]", "application/json")},
        )
        assert response.status_code == 400
        assert "not a split config file" in response.text
