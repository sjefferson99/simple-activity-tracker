"""Records storage, ranks and the Progress page (issue #190), end to end
through upload, delete, reanalyze and the web pages."""

from datetime import UTC, datetime

from tests.conftest import (
    HTMX,
    OTHER_USER_PASSWORD,
    create_user,
    upload_sample_activity,
    web_login,
)


def _ids(n: int) -> list[str]:
    return [f"33333333-3333-3333-3333-{i:012d}" for i in range(n)]


def _effort_rows(activity_id: str) -> dict[float, float]:
    from sqlalchemy import select

    from app.db import get_session_factory
    from app.models.best_effort import ActivityBestEffort

    with get_session_factory()() as session:
        rows = session.execute(
            select(ActivityBestEffort.distance_m, ActivityBestEffort.duration_s).where(
                ActivityBestEffort.activity_id == activity_id
            )
        )
        return {distance: duration for distance, duration in rows}


def _set_start_and_efforts(activity_id: str, started_at: str, one_km_s: float) -> None:
    """Moves an activity to a date and sets its 1 km best effort time."""
    from app.db import get_session_factory
    from app.models.activity import Activity
    from app.models.best_effort import ActivityBestEffort

    with get_session_factory()() as session:
        activity = session.get(Activity, activity_id)
        assert activity is not None
        activity.started_at = datetime.fromisoformat(started_at)
        effort = session.get(ActivityBestEffort, (activity_id, 1000.0))
        assert effort is not None
        effort.duration_s = one_km_s
        session.commit()


def _ranks(activity_id: str) -> dict[float, int]:
    from app.db import get_session_factory
    from app.models.activity import Activity
    from app.records import best_effort_ranks

    with get_session_factory()() as session:
        activity = session.get(Activity, activity_id)
        assert activity is not None
        return best_effort_ranks(session, activity)


def _upload(app_client, auth_headers, sample_gpx_bytes, client_id: str, activity_type="running"):
    response = upload_sample_activity(
        app_client,
        auth_headers,
        sample_gpx_bytes,
        client_activity_id=client_id,
        activity_type=activity_type,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# --- storage ------------------------------------------------------------------


def test_upload_stores_best_efforts_and_period_columns(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    from app.db import get_session_factory
    from app.models.activity_analysis import ActivityAnalysis

    activity_id = _upload(app_client, auth_headers, sample_gpx_bytes, _ids(1)[0])
    result = app_client.get(f"/api/v1/activities/{activity_id}", headers=auth_headers).json()[
        "analysis"
    ]["result"]

    expected = {e["distance_meters"]: e["duration_seconds"] for e in result["best_efforts"]}
    assert expected  # the 3 km fixture has 400 m, 1 km and 1 mile efforts
    assert _effort_rows(activity_id) == expected

    with get_session_factory()() as session:
        analysis = session.get(ActivityAnalysis, activity_id)
        assert analysis is not None
        assert analysis.elapsed_seconds == result["elapsed_seconds"]
        assert analysis.elevation_gain_m == result["elevation"]["gain_m"]


def test_deleting_an_activity_deletes_its_best_efforts(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    activity_id = _upload(app_client, auth_headers, sample_gpx_bytes, _ids(1)[0])
    assert _effort_rows(activity_id)
    response = app_client.delete(f"/api/v1/activities/{activity_id}", headers=auth_headers)
    assert response.status_code == 204
    assert _effort_rows(activity_id) == {}


def test_bulk_web_delete_deletes_best_efforts(app_client, auth_headers, sample_gpx_bytes) -> None:
    ids = [_upload(app_client, auth_headers, sample_gpx_bytes, cid) for cid in _ids(2)]
    web_login(app_client, "admin@example.com", "admin-password-123")
    response = app_client.post("/activities/bulk-delete", headers=HTMX, data={"activity_ids": ids})
    assert response.status_code == 200
    assert all(_effort_rows(i) == {} for i in ids)


def test_reanalyze_rewrites_best_efforts(app_client, auth_headers, sample_gpx_bytes) -> None:
    from sqlalchemy import delete

    from app.cli import reanalyze
    from app.db import get_session_factory
    from app.models.best_effort import ActivityBestEffort

    activity_id = _upload(app_client, auth_headers, sample_gpx_bytes, _ids(1)[0])
    before = _effort_rows(activity_id)
    with get_session_factory()() as session:
        session.execute(delete(ActivityBestEffort))
        session.commit()

    reanalyze(activity_id=activity_id, all_activities=False)

    assert _effort_rows(activity_id) == before


# --- ranks (D4: as of the activity's own date) ----------------------------------


def test_rank_is_as_of_the_activitys_date(app_client, auth_headers, sample_gpx_bytes) -> None:
    old, middle, new = (_upload(app_client, auth_headers, sample_gpx_bytes, cid) for cid in _ids(3))
    _set_start_and_efforts(old, "2026-01-01T08:00:00+00:00", 300.0)
    _set_start_and_efforts(middle, "2026-02-01T08:00:00+00:00", 280.0)  # PR when recorded
    _set_start_and_efforts(new, "2026-03-01T08:00:00+00:00", 290.0)

    assert _ranks(old)[1000.0] == 1
    # Still a PR on its own page, even though nothing later beat it here:
    assert _ranks(middle)[1000.0] == 1
    # Slower than one earlier effort, faster than the other.
    assert _ranks(new)[1000.0] == 2


def test_rank_ties_go_to_the_earlier_activity(app_client, auth_headers, sample_gpx_bytes) -> None:
    first, second = (_upload(app_client, auth_headers, sample_gpx_bytes, cid) for cid in _ids(2))
    _set_start_and_efforts(first, "2026-01-01T08:00:00+00:00", 300.0)
    _set_start_and_efforts(second, "2026-01-02T08:00:00+00:00", 300.0)
    assert _ranks(first)[1000.0] == 1
    assert _ranks(second)[1000.0] == 2


def test_rank_ignores_other_activity_types(app_client, auth_headers, sample_gpx_bytes) -> None:
    ids = _ids(2)
    run = _upload(app_client, auth_headers, sample_gpx_bytes, ids[0], "running")
    walk = _upload(app_client, auth_headers, sample_gpx_bytes, ids[1], "walking")
    _set_start_and_efforts(run, "2026-01-01T08:00:00+00:00", 200.0)
    _set_start_and_efforts(walk, "2026-01-02T08:00:00+00:00", 600.0)
    assert _ranks(walk)[1000.0] == 1


# --- activity page badges -----------------------------------------------------


def test_owner_sees_pr_badges_on_their_activity(app_client, auth_headers, sample_gpx_bytes) -> None:
    first, second = (_upload(app_client, auth_headers, sample_gpx_bytes, cid) for cid in _ids(2))
    _set_start_and_efforts(first, "2026-01-01T08:00:00+00:00", 300.0)
    _set_start_and_efforts(second, "2026-01-02T08:00:00+00:00", 310.0)
    web_login(app_client, "admin@example.com", "admin-password-123")

    page = app_client.get(f"/activities/{second}")
    assert page.status_code == 200
    assert 'data-testid="effort-rank">2nd best<' in page.text
    assert "1 mile" in page.text


def test_shared_activity_page_shows_no_ranks(app_client, auth_headers, sample_gpx_bytes) -> None:
    activity_id = _upload(app_client, auth_headers, sample_gpx_bytes, _ids(1)[0])
    viewer_id = create_user("viewer@example.com", "Viewer")
    web_login(app_client, "admin@example.com", "admin-password-123")
    granted = app_client.post(
        "/settings/shares", headers=HTMX, data={"viewer_id": viewer_id, "history": "on"}
    )
    assert granted.status_code == 200

    web_login(app_client, "viewer@example.com", OTHER_USER_PASSWORD)
    page = app_client.get(f"/shared/activities/{activity_id}")
    assert page.status_code == 200
    assert 'data-testid="best-efforts"' in page.text
    assert "effort-rank" not in page.text
    assert "up to this one's date" not in page.text


# --- Progress page ------------------------------------------------------------


def test_progress_page_empty_state(app_client, auth_headers) -> None:
    web_login(app_client, "admin@example.com", "admin-password-123")
    page = app_client.get("/progress", params={"tz": "Europe/London"})
    assert page.status_code == 200
    assert 'data-testid="progress-empty"' in page.text


def test_progress_page_requires_sign_in(app_client) -> None:
    response = app_client.get("/progress", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_progress_page_shows_records_and_this_weeks_totals(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    activity_id = _upload(app_client, auth_headers, sample_gpx_bytes, _ids(1)[0])
    _set_start_and_efforts(activity_id, datetime.now(UTC).isoformat(), 297.5)
    web_login(app_client, "admin@example.com", "admin-password-123")

    page = app_client.get("/progress", params={"tz": "Europe/London"})
    assert page.status_code == 200
    text = page.text
    assert "Europe/London" in text
    assert f'href="/activities/{activity_id}"' in text
    assert "4:57" in text  # the 1 km record
    assert 'data-testid="record-distance"' in text
    # This week's row counts the activity (current value first).
    week_row = text.split('data-testid="comparison-week"')[1].split("</tr>")[0]
    assert '<td class="text-right">1<div class="muted">0</div></td>' in week_row


def test_progress_page_shows_lifetime_totals_including_virtual(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    old, recent, zwift = (
        _upload(app_client, auth_headers, sample_gpx_bytes, cid) for cid in _ids(3)
    )
    _set_start_and_efforts(old, "2020-03-01T08:00:00+00:00", 300.0)
    _set_start_and_efforts(recent, datetime.now(UTC).isoformat(), 300.0)
    _set_start_and_efforts(zwift, datetime.now(UTC).isoformat(), 300.0)
    _set_virtual(zwift)
    web_login(app_client, "admin@example.com", "admin-password-123")

    text = app_client.get("/progress", params={"tz": "UTC"}).text
    row = text.split('data-testid="comparison-lifetime"')[1].split("</tr>")[0]
    assert 'datetime="2020-03-01T08:00:00' in row  # since the first activity
    assert '<td class="text-right">3</td>' in row  # virtual ones count in totals
    assert '<td class="text-right">9.05 km</td>' in row  # 3 x the ~3.02 km fixture


def test_progress_page_only_counts_your_own_activities(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    _upload(app_client, auth_headers, sample_gpx_bytes, _ids(1)[0])
    create_user("other@example.com", "Other")
    web_login(app_client, "other@example.com", OTHER_USER_PASSWORD)

    page = app_client.get("/progress", params={"tz": "UTC"})
    assert page.status_code == 200
    assert 'data-testid="progress-empty"' in page.text


def test_progress_page_type_tabs_and_unknown_type_fallback(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    ids = _ids(3)
    _upload(app_client, auth_headers, sample_gpx_bytes, ids[0], "running")
    _upload(app_client, auth_headers, sample_gpx_bytes, ids[1], "running")
    _upload(app_client, auth_headers, sample_gpx_bytes, ids[2], "cycling")
    web_login(app_client, "admin@example.com", "admin-password-123")

    # Most-used type first, and the default.
    default = app_client.get("/progress", params={"tz": "UTC"}).text
    assert default.index(">Running</a>") < default.index(">Cycling</a>")
    assert 'aria-current="page">Running</a>' in default

    cycling = app_client.get("/progress", params={"type": "cycling", "tz": "UTC"}).text
    assert 'aria-current="page">Cycling</a>' in cycling
    assert "Speed</th>" in cycling  # cycling records show km/h, not pace

    unknown = app_client.get("/progress", params={"type": "rowing", "tz": "UTC"}).text
    assert 'aria-current="page">Running</a>' in unknown


def test_all_activities_tab_totals_every_type_without_trends_or_records(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    ids = _ids(3)
    for client_id, activity_type in zip(ids, ("running", "cycling", "walking"), strict=True):
        _upload(app_client, auth_headers, sample_gpx_bytes, client_id, activity_type)
    web_login(app_client, "admin@example.com", "admin-password-123")

    default = app_client.get("/progress", params={"tz": "UTC"}).text
    assert ">All activities</a>" in default

    text = app_client.get("/progress", params={"type": "all", "tz": "UTC"}).text
    assert 'aria-current="page">All activities</a>' in text
    row = text.split('data-testid="comparison-lifetime"')[1].split("</tr>")[0]
    assert '<td class="text-right">3</td>' in row
    assert 'id="period-chart"' in text
    assert 'id="trend-chart"' not in text
    assert 'data-testid="progress-records"' not in text


def test_all_activities_tab_is_hidden_with_only_one_type(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    _upload(app_client, auth_headers, sample_gpx_bytes, _ids(1)[0])
    web_login(app_client, "admin@example.com", "admin-password-123")

    assert ">All activities</a>" not in app_client.get("/progress", params={"tz": "UTC"}).text
    # A stale ?type=all link falls back to the only type.
    fallback = app_client.get("/progress", params={"type": "all", "tz": "UTC"}).text
    assert 'aria-current="page">Running</a>' in fallback


def test_progress_page_falls_back_to_utc_for_a_bad_timezone(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    _upload(app_client, auth_headers, sample_gpx_bytes, _ids(1)[0])
    web_login(app_client, "admin@example.com", "admin-password-123")
    page = app_client.get("/progress", params={"tz": "Mars/Olympus_Mons"})
    assert page.status_code == 200
    assert "Periods use your timezone (UTC)" in page.text


def test_nav_links_to_progress(app_client, auth_headers) -> None:
    web_login(app_client, "admin@example.com", "admin-password-123")
    assert '<a href="/progress">Progress</a>' in app_client.get("/").text


# --- virtual activities -------------------------------------------------------


def _set_virtual(activity_id: str, is_virtual: bool = True) -> None:
    from app.db import get_session_factory
    from app.models.activity import Activity

    with get_session_factory()() as session:
        activity = session.get(Activity, activity_id)
        assert activity is not None
        activity.is_virtual = is_virtual
        session.commit()


def _is_virtual(activity_id: str) -> bool:
    from app.db import get_session_factory
    from app.models.activity import Activity

    with get_session_factory()() as session:
        activity = session.get(Activity, activity_id)
        assert activity is not None
        return activity.is_virtual


def test_virtual_activity_never_ranks_or_pushes_outdoor_down(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    zwift, road = (_upload(app_client, auth_headers, sample_gpx_bytes, cid) for cid in _ids(2))
    _set_start_and_efforts(zwift, "2026-01-01T08:00:00+00:00", 100.0)  # far faster, earlier
    _set_start_and_efforts(road, "2026-01-02T08:00:00+00:00", 300.0)
    _set_virtual(zwift)

    assert _ranks(road)[1000.0] == 1
    assert _ranks(zwift) == {}


def test_progress_records_leave_out_virtual_activities(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    zwift, road = (_upload(app_client, auth_headers, sample_gpx_bytes, cid) for cid in _ids(2))
    _set_start_and_efforts(zwift, datetime.now(UTC).isoformat(), 100.0)
    _set_start_and_efforts(road, datetime.now(UTC).isoformat(), 300.0)
    _set_virtual(zwift)
    web_login(app_client, "admin@example.com", "admin-password-123")

    text = app_client.get("/progress", params={"tz": "UTC"}).text
    records = text.split('data-testid="progress-records"')[1]
    assert f'href="/activities/{road}"' in records
    assert f'href="/activities/{zwift}"' not in records
    assert "1:40" not in records  # the virtual 100 s km
    # ...but both still count in this week's totals.
    week_row = text.split('data-testid="comparison-week"')[1].split("</tr>")[0]
    assert '<td class="text-right">2<div class="muted">' in week_row


def test_virtual_flag_is_set_and_cleared_from_the_edit_form(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    activity_id = _upload(app_client, auth_headers, sample_gpx_bytes, _ids(1)[0])
    web_login(app_client, "admin@example.com", "admin-password-123")
    fields = {"title": "Zwift", "notes": "", "device_name": ""}

    ticked = app_client.patch(
        f"/activities/{activity_id}", headers=HTMX, data={**fields, "is_virtual": "on"}
    )
    assert ticked.status_code == 200
    assert _is_virtual(activity_id)
    page = app_client.get(f"/activities/{activity_id}").text
    assert 'data-testid="virtual-badge"' in page
    assert 'name="is_virtual" checked' in page
    assert "Virtual activities aren't ranked" in page
    assert "effort-rank" not in page

    unticked = app_client.patch(f"/activities/{activity_id}", headers=HTMX, data=fields)
    assert unticked.status_code == 200
    assert not _is_virtual(activity_id)


def test_strava_virtual_ride_imports_as_virtual(app_client, auth_headers, sample_gpx_bytes) -> None:
    import gzip

    from tests.test_strava_import import _CSV_HEADER, _build_export_zip, _csv_row, _import_via_api

    archive = _build_export_zip(
        _CSV_HEADER
        + _csv_row("1", "Sep 9, 2026, 8:58:03 PM", "Zwift", "Virtual Ride", "activities/1.gpx.gz")
        + _csv_row("2", "Sep 8, 2026, 8:58:03 PM", "Commute", "Ride", "activities/2.gpx.gz"),
        {
            "activities/1.gpx.gz": gzip.compress(sample_gpx_bytes),
            "activities/2.gpx.gz": gzip.compress(sample_gpx_bytes),
        },
    )
    assert _import_via_api(app_client, auth_headers, archive)["imported"] == 2

    listing = app_client.get("/api/v1/activities", headers=auth_headers).json()["activities"]
    by_title = {a["title"]: a["id"] for a in listing}
    assert _is_virtual(by_title["Zwift"])
    assert not _is_virtual(by_title["Commute"])


def test_virtual_flag_survives_backup_export_and_import(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    import io
    import json
    import zipfile

    activity_id = _upload(app_client, auth_headers, sample_gpx_bytes, _ids(1)[0])
    _set_virtual(activity_id)
    exported = app_client.post("/api/v1/activities/export", headers=auth_headers, json={})
    assert exported.status_code == 200
    manifest = json.loads(zipfile.ZipFile(io.BytesIO(exported.content)).read("manifest.json"))
    assert manifest["activities"][0]["is_virtual"] is True

    app_client.delete(f"/api/v1/activities/{activity_id}", headers=auth_headers)
    imported = app_client.post(
        "/api/v1/activities/import",
        headers=auth_headers,
        files={"archive": ("export.zip", exported.content, "application/zip")},
    )
    assert imported.json()["imported"] == 1
    new_id = app_client.get("/api/v1/activities", headers=auth_headers).json()["activities"][0][
        "id"
    ]
    assert _is_virtual(new_id)
