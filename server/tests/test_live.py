"""Live tracking (issue #130 phase B, docs/LIVE-TRACKING-PLAN.md §2.3 to §3):
the phone's upload protocol, the sharing settings the phone uses, and who
may watch a live session. Live access is checked on every request and ends
when the activity finishes."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import (
    HTMX,
    OTHER_USER_PASSWORD,
    bearer_headers,
    create_user,
    make_summary,
    web_login,
)

OWNER_EMAIL, OWNER_PASSWORD = "admin@example.com", "admin-password-123"
VIEWER_EMAIL = "viewer@example.com"
CID = "13013013-0130-0130-0130-130130130130"


def _points(start: int, count: int, segment: int = 0) -> list[dict]:
    base = datetime(2026, 1, 1, 7, 0, tzinfo=UTC)
    return [
        {
            "t": (base + timedelta(seconds=i)).isoformat(),
            "lat": 51.5 + i * 0.0001,
            "lon": -0.12,
            "ele": 20.0,
            "accuracy": 5.0,
            "speed": 3.0,
            "segment": segment,
        }
        for i in range(start, start + count)
    ]


def _metrics(distance: float = 1234.0) -> dict:
    return {
        "distance_meters": distance,
        "elapsed_seconds": 400.0,
        "moving_seconds": 390.0,
        "avg_speed_mps": 3.1,
        "current_speed_mps": 3.3,
        "splits": [
            {"index": 1, "duration_seconds": 320.0, "avg_speed_mps": 3.1, "distance_m": 1000}
        ],
    }


def _start(client, headers, cid: str = CID) -> dict:
    response = client.put(
        f"/api/v1/live/{cid}",
        headers=headers,
        json={"activity_type": "running", "started_at": "2026-01-01T07:00:00Z"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _send(client, headers, from_index: int, points: list, *, state="active", metrics=None, cid=CID):
    body: dict = {"from_index": from_index, "points": points, "state": state}
    if metrics is not None:
        body["metrics"] = metrics
    return client.post(f"/api/v1/live/{cid}/points", headers=headers, json=body)


def _live_session_id(cid: str = CID) -> str:
    from app.db import get_session_factory
    from app.models.live import LiveSession

    with get_session_factory()() as session:
        live = session.query(LiveSession).filter_by(client_activity_id=cid).one()
        return live.id


def _set_last_update(session_id: str, when: datetime) -> None:
    from app.db import get_session_factory
    from app.models.live import LiveSession

    with get_session_factory()() as session:
        live = session.get(LiveSession, session_id)
        assert live is not None
        live.last_update_at = when
        session.commit()


@pytest.fixture
def viewer_id(app_client, auth_headers) -> str:
    return create_user(VIEWER_EMAIL, "Vera Viewer")


def _grant(client, viewer_id: str, *, live: bool = True, history: bool = False) -> None:
    web_login(client, OWNER_EMAIL, OWNER_PASSWORD)
    data = {"viewer_id": viewer_id}
    if live:
        data["live"] = "on"
    if history:
        data["history"] = "on"
    assert client.post("/settings/shares", headers=HTMX, data=data).status_code == 200


def _as_viewer(client) -> None:
    web_login(client, VIEWER_EMAIL, OTHER_USER_PASSWORD)


# --- upload protocol ---------------------------------------------------------


def test_put_creates_once_and_is_idempotent(app_client, auth_headers):
    assert _start(app_client, auth_headers) == {"next_index": 0, "state": "active"}
    first_id = _live_session_id()
    assert _start(app_client, auth_headers) == {"next_index": 0, "state": "active"}
    assert _live_session_id() == first_id


def test_points_append_and_retries_are_no_ops(app_client, auth_headers):
    _start(app_client, auth_headers)
    first = _send(app_client, auth_headers, 0, _points(0, 3), metrics=_metrics())
    assert first.json() == {"next_index": 3, "state": "active"}
    # The same batch again (a retry after a timeout): nothing new stored.
    assert _send(app_client, auth_headers, 0, _points(0, 3)).json()["next_index"] == 3
    # Overlapping batch: only the unseen tail is stored.
    assert _send(app_client, auth_headers, 2, _points(2, 3)).json()["next_index"] == 5

    from app.db import get_session_factory
    from app.models.live import LivePoint

    with get_session_factory()() as session:
        idxs = [p.idx for p in session.query(LivePoint).order_by(LivePoint.idx)]
        assert idxs == [0, 1, 2, 3, 4]


def test_gap_is_409_with_the_index_to_resend_from(app_client, auth_headers):
    _start(app_client, auth_headers)
    _send(app_client, auth_headers, 0, _points(0, 2))
    response = _send(app_client, auth_headers, 7, _points(7, 2))
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "index_gap"
    assert error["next_index"] == 2


def test_points_before_put_is_404(app_client, auth_headers):
    assert _send(app_client, auth_headers, 0, _points(0, 1)).status_code == 404


def test_sessions_are_per_user(app_client, auth_headers, viewer_id):
    _start(app_client, auth_headers)
    other = bearer_headers(app_client, VIEWER_EMAIL, OTHER_USER_PASSWORD)
    # Someone else's client id is just an unknown session to me.
    assert _send(app_client, other, 0, _points(0, 1)).status_code == 404
    assert app_client.delete(f"/api/v1/live/{CID}", headers=other).status_code == 404


@pytest.mark.parametrize(
    "bad_point",
    [{"lat": 91}, {"lon": -181}, {"speed": -1}, {"accuracy": float("nan")}, {"segment": -1}],
)
def test_invalid_points_are_rejected(app_client, auth_headers, bad_point):
    _start(app_client, auth_headers)
    point = {**_points(0, 1)[0], **bad_point}
    response = app_client.post(
        f"/api/v1/live/{CID}/points",
        headers=auth_headers,
        content=json.dumps({"from_index": 0, "points": [point]}, allow_nan=True),
    )
    assert response.status_code == 422


def test_batch_and_session_size_limits(app_client, auth_headers, monkeypatch):
    _start(app_client, auth_headers)
    too_many = _send(app_client, auth_headers, 0, _points(0, 2001))
    assert too_many.status_code == 422

    import app.api.v1.live as live_api

    monkeypatch.setattr(live_api, "LIVE_POINTS_MAX_PER_SESSION", 5)
    assert _send(app_client, auth_headers, 0, _points(0, 4)).status_code == 200
    assert _send(app_client, auth_headers, 4, _points(4, 2)).status_code == 413


def test_bad_client_activity_id_is_rejected(app_client, auth_headers):
    response = app_client.put(
        "/api/v1/live/not-a-uuid!",
        headers=auth_headers,
        json={"activity_type": "running", "started_at": "2026-01-01T07:00:00Z"},
    )
    assert response.status_code == 422


def test_live_uploads_are_rate_limited(app_client, auth_headers, monkeypatch):
    from app.auth.rate_limit import live_upload_rate_limiter

    monkeypatch.setattr(live_upload_rate_limiter, "_max_events", 2)
    _start(app_client, auth_headers)
    assert _send(app_client, auth_headers, 0, _points(0, 1)).status_code == 200
    assert _send(app_client, auth_headers, 1, _points(1, 1)).status_code == 429


def test_metrics_and_state_are_stored(app_client, auth_headers):
    _start(app_client, auth_headers)
    _send(app_client, auth_headers, 0, _points(0, 2), state="paused", metrics=_metrics(999.0))

    from app.db import get_session_factory
    from app.models.live import LiveSession

    with get_session_factory()() as session:
        live = session.query(LiveSession).one()
        assert live.state == "paused"
        assert live.latest_metrics["distance_meters"] == 999.0
        assert live.finished_at is None

    _send(app_client, auth_headers, 2, [], state="finished")
    with get_session_factory()() as session:
        live = session.query(LiveSession).one()
        assert live.state == "finished"
        assert live.finished_at is not None


def test_final_upload_links_the_session_and_closes_it(app_client, auth_headers, sample_gpx_bytes):
    _start(app_client, auth_headers)
    _send(app_client, auth_headers, 0, _points(0, 3))
    upload = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(make_summary(CID))},
        files={"gpx": ("a.gpx", sample_gpx_bytes, "application/gpx+xml")},
    )
    assert upload.status_code == 201
    activity_id = upload.json()["id"]

    from app.db import get_session_factory
    from app.models.live import LivePoint, LiveSession

    with get_session_factory()() as session:
        live = session.query(LiveSession).one()
        assert live.activity_id == activity_id
        assert live.state == "finished"
        assert session.query(LivePoint).count() == 0

    # The phone is told to stop: the activity is saved.
    late = _send(app_client, auth_headers, 3, _points(3, 1))
    assert late.status_code == 410
    assert late.json()["error"]["code"] == "session_closed"
    assert _start_status(app_client, auth_headers) == 410
    # Discarding the run on the phone can't delete a saved activity's session.
    assert app_client.delete(f"/api/v1/live/{CID}", headers=auth_headers).status_code == 404

    # Deleting the activity takes its live session with it.
    assert (
        app_client.delete(f"/api/v1/activities/{activity_id}", headers=auth_headers).status_code
        == 204
    )
    with get_session_factory()() as session:
        assert session.query(LiveSession).count() == 0


def _start_status(client, headers) -> int:
    return client.put(
        f"/api/v1/live/{CID}",
        headers=headers,
        json={"activity_type": "running", "started_at": "2026-01-01T07:00:00Z"},
    ).status_code


def test_upload_with_no_live_session_is_unaffected(app_client, auth_headers, sample_gpx_bytes):
    upload = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(make_summary(CID))},
        files={"gpx": ("a.gpx", sample_gpx_bytes, "application/gpx+xml")},
    )
    assert upload.status_code == 201


def test_discarding_a_run_deletes_the_session(app_client, auth_headers):
    _start(app_client, auth_headers)
    _send(app_client, auth_headers, 0, _points(0, 3))
    assert app_client.delete(f"/api/v1/live/{CID}", headers=auth_headers).status_code == 204

    from app.db import get_session_factory
    from app.models.live import LivePoint, LiveSession

    with get_session_factory()() as session:
        assert session.query(LiveSession).count() == 0
        assert session.query(LivePoint).count() == 0


def test_sessions_older_than_30_days_are_purged(app_client, auth_headers):
    _start(app_client, auth_headers, cid="00000000-0000-0000-0000-000000000001")
    _send(app_client, auth_headers, 0, _points(0, 2), cid="00000000-0000-0000-0000-000000000001")
    old_id = _live_session_id("00000000-0000-0000-0000-000000000001")
    _set_last_update(old_id, datetime.now(UTC) - timedelta(days=31))

    _start(app_client, auth_headers)  # a new session triggers the sweep

    from app.db import get_session_factory
    from app.models.live import LivePoint, LiveSession

    with get_session_factory()() as session:
        assert session.get(LiveSession, old_id) is None
        assert session.query(LivePoint).count() == 0


@pytest.mark.parametrize("via", ["api", "web"])
def test_admin_can_delete_a_user_with_live_sessions(app_client, auth_headers, viewer_id, via):
    viewer_headers = bearer_headers(app_client, VIEWER_EMAIL, OTHER_USER_PASSWORD)
    _start(app_client, viewer_headers)
    _send(app_client, viewer_headers, 0, _points(0, 3))
    if via == "api":
        response = app_client.delete(f"/api/v1/admin/users/{viewer_id}", headers=auth_headers)
        assert response.status_code == 204
    else:
        web_login(app_client, OWNER_EMAIL, OWNER_PASSWORD)
        assert app_client.delete(f"/admin/users/{viewer_id}", headers=HTMX).status_code == 200

    from app.db import get_session_factory
    from app.models.live import LivePoint, LiveSession

    with get_session_factory()() as session:
        assert session.query(LiveSession).count() == 0
        assert session.query(LivePoint).count() == 0


# --- sharing settings for the phone ---------------------------------------------


def test_user_directory_lists_enabled_others_without_emails(app_client, auth_headers, viewer_id):
    create_user("gone@example.com", "Gone", disabled=True)
    users = app_client.get("/api/v1/users", headers=auth_headers).json()["users"]
    assert users == [{"id": viewer_id, "display_name": "Vera Viewer"}]


def test_put_live_sharing_sets_live_only_and_the_pause(app_client, auth_headers, viewer_id):
    other_id = create_user("other@example.com", "Otto")
    # Otto already has History from the web; the phone's update must keep it.
    _grant(app_client, other_id, live=False, history=True)

    response = app_client.put(
        "/api/v1/me/live-sharing",
        headers=auth_headers,
        json={"live_sharing_paused": True, "live_viewer_ids": [viewer_id]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["live_sharing_paused"] is True
    shares = {s["viewer_id"]: s for s in body["shares"]}
    assert shares[viewer_id]["can_view_live"] is True
    assert shares[viewer_id]["can_view_history"] is False
    assert shares[other_id]["can_view_live"] is False
    assert shares[other_id]["can_view_history"] is True

    # Removing Vera from the live list deletes her now-empty grant.
    app_client.put(
        "/api/v1/me/live-sharing",
        headers=auth_headers,
        json={"live_sharing_paused": False, "live_viewer_ids": []},
    )
    mine = app_client.get("/api/v1/me/shares", headers=auth_headers).json()
    assert mine["live_sharing_paused"] is False
    assert [s["viewer_id"] for s in mine["shares"]] == [other_id]


@pytest.mark.parametrize("bad", ["self", "disabled", "unknown"])
def test_put_live_sharing_rejects_unshareable_users(app_client, auth_headers, bad):
    me = app_client.get("/api/v1/me", headers=auth_headers).json()["id"]
    bad_id = {
        "self": me,
        "disabled": create_user("gone@example.com", "Gone", disabled=True),
        "unknown": "00000000-0000-0000-0000-000000000000",
    }[bad]
    response = app_client.put(
        "/api/v1/me/live-sharing",
        headers=auth_headers,
        json={"live_sharing_paused": False, "live_viewer_ids": [bad_id]},
    )
    assert response.status_code == 400
    assert app_client.get("/api/v1/me/shares", headers=auth_headers).json()["shares"] == []


# --- who can watch ---------------------------------------------------------------


@pytest.fixture
def running(app_client, auth_headers) -> str:
    """The owner (admin) has a live run with 3 points; returns its id."""
    _start(app_client, auth_headers)
    _send(app_client, auth_headers, 0, _points(0, 3), metrics=_metrics())
    return _live_session_id()


def test_owner_always_sees_their_own_live_page(app_client, running):
    web_login(app_client, OWNER_EMAIL, OWNER_PASSWORD)
    page = app_client.get(f"/live/{running}")
    assert page.status_code == 200
    assert "Your live run" in page.text
    assert "Nobody has Live access" in page.text
    poll = app_client.get(f"/live/{running}/poll").json()
    assert poll["status"] == "live"
    assert len(poll["points"]) == 3
    assert poll["metrics"]["distance_meters"] == 1234.0
    assert app_client.get("/").text.count(f'href="/live/{running}"') == 1


@pytest.mark.parametrize("grant", ["none", "history_only"])
def test_viewer_without_a_live_grant_sees_nothing(app_client, running, viewer_id, grant):
    if grant == "history_only":
        _grant(app_client, viewer_id, live=False, history=True)
    _as_viewer(app_client)
    assert app_client.get(f"/live/{running}").status_code == 404
    assert app_client.get(f"/live/{running}/poll").status_code == 404
    assert f"/live/{running}" not in app_client.get("/", params={"tab": "shared"}).text


def test_viewer_with_a_live_grant_can_watch(app_client, running, viewer_id):
    _grant(app_client, viewer_id)
    _as_viewer(app_client)

    page = app_client.get(f"/live/{running}")
    assert page.status_code == 200
    assert "Admin&#39;s live run" in page.text
    assert "Delete live activity" not in page.text
    poll = app_client.get(f"/live/{running}/poll").json()
    assert poll["status"] == "live"
    assert len(poll["points"]) == 3
    # Polls fetch only what's new.
    assert app_client.get(f"/live/{running}/poll", params={"from": 2}).json()["points"] == [
        {"lat": 51.5002, "lon": -0.12, "segment": 0, "t": "2026-01-01T07:00:02+00:00"}
    ]
    shared_tab = app_client.get("/", params={"tab": "shared"}).text
    assert f'href="/live/{running}"' in shared_tab
    assert "Admin&#39;s run" in shared_tab
    # A viewer can't delete it.
    assert app_client.delete(f"/live/{running}", headers=HTMX).status_code == 404


@pytest.mark.parametrize("change", ["revoke", "untick_live", "pause_web", "pause_api", "disable"])
def test_owner_changes_cut_a_viewer_off_on_the_next_poll(
    app_client, auth_headers, running, viewer_id, change
):
    _grant(app_client, viewer_id)
    _as_viewer(app_client)
    assert app_client.get(f"/live/{running}/poll").status_code == 200

    web_login(app_client, OWNER_EMAIL, OWNER_PASSWORD)
    if change == "revoke":
        app_client.delete(f"/settings/shares/{viewer_id}", headers=HTMX)
    elif change == "untick_live":
        app_client.patch(f"/settings/shares/{viewer_id}", headers=HTMX, data={"history": "on"})
    elif change == "pause_web":
        app_client.put("/settings/live-sharing", headers=HTMX, data={"paused": "on"})
    elif change == "pause_api":
        app_client.put(
            "/api/v1/me/live-sharing",
            headers=auth_headers,
            json={"live_sharing_paused": True, "live_viewer_ids": [viewer_id]},
        )
    else:
        from app.db import get_session_factory
        from app.models.user import User

        with get_session_factory()() as session:
            owner = session.query(User).filter_by(email=OWNER_EMAIL).one()
            owner.disabled_at = datetime.now(UTC)
            session.commit()

    _as_viewer(app_client)
    assert app_client.get(f"/live/{running}/poll").status_code == 404
    assert app_client.get(f"/live/{running}").status_code == 404


def test_pause_keeps_the_live_list(app_client, running, viewer_id):
    _grant(app_client, viewer_id)
    paused = app_client.put("/settings/live-sharing", headers=HTMX, data={"paused": "on"})
    assert "Nobody can watch your activities live" in paused.text
    resumed = app_client.put("/settings/live-sharing", headers=HTMX)
    assert "Vera Viewer" in resumed.text
    _as_viewer(app_client)
    assert app_client.get(f"/live/{running}/poll").status_code == 200


def test_live_access_ends_at_completion_with_no_data(app_client, auth_headers, running, viewer_id):
    _grant(app_client, viewer_id)
    _send(app_client, auth_headers, 3, [], state="finished")
    _as_viewer(app_client)

    poll = app_client.get(f"/live/{running}/poll").json()
    assert poll == {"status": "finished", "activity_url": None}
    page = app_client.get(f"/live/{running}")
    assert page.status_code == 200
    assert "This activity has finished." in page.text
    assert 'id="map"' not in page.text
    assert "leaflet.js" not in page.text
    assert f"/live/{running}" not in app_client.get("/", params={"tab": "shared"}).text


@pytest.mark.parametrize("has_history", [True, False])
def test_finished_activity_link_only_with_history_access(
    app_client, auth_headers, sample_gpx_bytes, running, viewer_id, has_history
):
    _grant(app_client, viewer_id, live=True, history=has_history)
    upload = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(make_summary(CID))},
        files={"gpx": ("a.gpx", sample_gpx_bytes, "application/gpx+xml")},
    )
    activity_id = upload.json()["id"]

    _as_viewer(app_client)
    poll = app_client.get(f"/live/{running}/poll").json()
    expected = f"/shared/activities/{activity_id}" if has_history else None
    assert poll == {"status": "finished", "activity_url": expected}

    web_login(app_client, OWNER_EMAIL, OWNER_PASSWORD)
    owner_poll = app_client.get(f"/live/{running}/poll").json()
    assert owner_poll["status"] == "finished"
    assert owner_poll["activity_url"] == f"/activities/{activity_id}"
    # Saved sessions leave the owner's "Live and unsaved" list.
    assert f'href="/live/{running}"' not in app_client.get("/").text


def test_stale_sessions_drop_off_for_viewers_but_not_the_owner(app_client, running, viewer_id):
    _grant(app_client, viewer_id)
    _set_last_update(running, datetime.now(UTC) - timedelta(hours=13))

    _as_viewer(app_client)
    assert app_client.get(f"/live/{running}/poll").status_code == 404
    assert f"/live/{running}" not in app_client.get("/", params={"tab": "shared"}).text

    web_login(app_client, OWNER_EMAIL, OWNER_PASSWORD)
    assert app_client.get(f"/live/{running}/poll").status_code == 200


def test_owner_can_delete_an_unsaved_live_session_from_the_web(app_client, running):
    web_login(app_client, OWNER_EMAIL, OWNER_PASSWORD)
    assert app_client.delete(f"/live/{running}").status_code == 403  # htmx header required
    response = app_client.delete(f"/live/{running}", headers=HTMX)
    assert response.status_code == 200
    assert app_client.get(f"/live/{running}").status_code == 404


def test_live_routes_require_sign_in(app_client, running):
    app_client.cookies.clear()
    assert app_client.get(f"/live/{running}", follow_redirects=False).status_code == 303
    assert app_client.get(f"/live/{running}/poll", follow_redirects=False).status_code == 303


# --- the self-refreshing Live now list ---------------------------------------------


def test_live_now_list_refreshes_itself(app_client, viewer_id):
    _grant(app_client, viewer_id)
    _as_viewer(app_client)
    page = app_client.get("/", params={"tab": "shared"}).text
    # Always present (even empty) so a run that starts later can appear.
    assert 'id="live-now"' in page
    assert 'hx-get="/live-now?tab=shared"' in page
    assert 'hx-trigger="every 30s"' in page


def test_live_now_fragment_shows_runs_as_they_start_and_end(app_client, auth_headers, viewer_id):
    _grant(app_client, viewer_id)
    _as_viewer(app_client)
    before = app_client.get("/live-now", params={"tab": "shared"}, headers={"HX-Request": "true"})
    assert before.status_code == 200
    assert "/live/" not in before.text
    assert "Nobody is sharing a live activity with you right now." in before.text

    _start(app_client, auth_headers)
    _send(app_client, auth_headers, 0, _points(0, 2))
    session_id = _live_session_id()
    during = app_client.get("/live-now", params={"tab": "shared"}).text
    assert f'href="/live/{session_id}"' in during
    assert "Admin&#39;s run" in during

    _send(app_client, auth_headers, 2, [], state="finished")
    after = app_client.get("/live-now", params={"tab": "shared"}).text
    assert f"/live/{session_id}" not in after

    web_login(app_client, OWNER_EMAIL, OWNER_PASSWORD)
    mine = app_client.get("/live-now", params={"tab": "mine"}).text
    assert f'href="/live/{session_id}"' in mine
    assert "Finished, not uploaded yet" in mine

    other = app_client.get("/", params={"tab": "mine"}).text
    assert "Live and unsaved" in other


def test_live_now_card_is_hidden_on_mine_when_empty(app_client, auth_headers):
    web_login(app_client, OWNER_EMAIL, OWNER_PASSWORD)
    page = app_client.get("/").text
    # Still polling, so a run started on the phone appears on its own...
    assert 'hx-get="/live-now?tab=mine"' in page
    # ...but no card or empty message on Mine; that's only on Shared.
    assert "Live and unsaved" not in page
    assert "Nobody is sharing a live activity" not in page


def test_live_now_fragment_requires_sign_in(app_client):
    app_client.cookies.clear()
    assert app_client.get("/live-now", follow_redirects=False).status_code == 303
