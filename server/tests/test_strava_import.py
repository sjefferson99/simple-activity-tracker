import gzip
import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

_FIXTURE_DIR = Path(__file__).parent / "fixtures"

_SAMPLE_TCX = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">'
    b'<Activities><Activity Sport="Ride"><Id>2026-01-01T00:00:00Z</Id>'
    b'<Lap StartTime="2026-01-01T00:00:00Z"><Track>'
    b"<Trackpoint><Time>2026-01-01T00:00:00Z</Time>"
    b"<Position><LatitudeDegrees>1</LatitudeDegrees><LongitudeDegrees>1</LongitudeDegrees></Position>"
    b"</Trackpoint>"
    b"<Trackpoint><Time>2026-01-01T00:00:01Z</Time>"
    b"<Position><LatitudeDegrees>1.001</LatitudeDegrees><LongitudeDegrees>1</LongitudeDegrees></Position>"
    b"</Trackpoint>"
    b"</Track></Lap></Activity></Activities></TrainingCenterDatabase>"
)

_CSV_HEADER = (
    "Activity ID,Activity Date,Activity Name,Activity Description,Activity Type,Filename\n"
)


def _csv_row(
    activity_id: str,
    date: str,
    name: str,
    activity_type: str,
    filename: str,
    description: str = "",
) -> str:
    return f'{activity_id},"{date}",{name},{description},{activity_type},{filename}\n'


def _build_export_zip(
    csv_content: str, files: dict[str, bytes], extra_entries: dict[str, bytes] | None = None
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("activities.csv", csv_content)
        for filename, data in files.items():
            archive.writestr(filename, data)
        for filename, data in (extra_entries or {}).items():
            archive.writestr(filename, data)
    return buf.getvalue()


def _default_export(sample_gpx_bytes: bytes) -> bytes:
    fit_bytes = (_FIXTURE_DIR / "sample.fit").read_bytes()
    csv_content = (
        _CSV_HEADER
        + _csv_row("111", "Sep 9, 2026, 8:58:03 PM", "Morning Run", "Run", "activities/111.gpx.gz")
        + _csv_row(
            "222", "Sep 8, 2026, 5:09:03 PM", "Evening Ride", "Ride", "activities/222.fit.gz"
        )
        + _csv_row("333", "Sep 7, 2026, 9:00:00 AM", "A walk", "Walk", "activities/333.tcx.gz")
    )
    return _build_export_zip(
        csv_content,
        {
            "activities/111.gpx.gz": gzip.compress(sample_gpx_bytes),
            "activities/222.fit.gz": gzip.compress(fit_bytes),
            "activities/333.tcx.gz": gzip.compress(_SAMPLE_TCX),
        },
        extra_entries={"profile.csv": b"irrelevant"},
    )


def _other_user_headers(app_client) -> dict[str, str]:
    from app.auth.passwords import hash_password
    from app.db import get_session_factory
    from app.models.user import User
    from app.repositories.users import SqlAlchemyUserRepository

    with get_session_factory()() as session:
        now = datetime.now(UTC)
        other = User(
            email="other@example.com",
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
        json={"email": "other@example.com", "password": "other-password-123", "device_name": "x"},
    )
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_imports_gpx_fit_and_tcx_rows_with_correct_type_and_tags(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    archive = _default_export(sample_gpx_bytes)
    response = app_client.post(
        "/api/v1/activities/import/strava",
        headers=auth_headers,
        files={"archive": ("strava_export.zip", archive, "application/zip")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == 3
    assert body["skipped"] == 0
    assert body["failed"] == 0

    activities = app_client.get("/api/v1/activities", headers=auth_headers).json()["activities"]
    by_title = {a["title"]: a for a in activities}

    run = app_client.get(
        f"/api/v1/activities/{by_title['Morning Run']['id']}", headers=auth_headers
    )
    run_body = run.json()
    assert run_body["activity_type"] == "running"
    assert {t["name"] for t in run_body["tags"]} == {"running", "Strava"}
    assert run_body["source_platform"] == "strava_import"

    ride = app_client.get(
        f"/api/v1/activities/{by_title['Evening Ride']['id']}", headers=auth_headers
    ).json()
    assert ride["activity_type"] == "cycling"
    assert {t["name"] for t in ride["tags"]} == {"cycling", "Strava"}

    walk = app_client.get(
        f"/api/v1/activities/{by_title['A walk']['id']}", headers=auth_headers
    ).json()
    assert walk["activity_type"] == "running"  # default, per the confirmed decision
    assert {t["name"] for t in walk["tags"]} == {"Strava"}  # no type tag for Walk


def test_reimporting_the_same_export_is_idempotent(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    archive = _default_export(sample_gpx_bytes)
    app_client.post(
        "/api/v1/activities/import/strava",
        headers=auth_headers,
        files={"archive": ("strava_export.zip", archive, "application/zip")},
    )
    response = app_client.post(
        "/api/v1/activities/import/strava",
        headers=auth_headers,
        files={"archive": ("strava_export.zip", archive, "application/zip")},
    )
    body = response.json()
    assert body == {
        "imported": 0,
        "skipped": 3,
        "failed": 0,
        "items": [
            {
                "client_activity_id": "strava:111",
                "status": "skipped",
                "reason": "Activity already exists",
            },
            {
                "client_activity_id": "strava:222",
                "status": "skipped",
                "reason": "Activity already exists",
            },
            {
                "client_activity_id": "strava:333",
                "status": "skipped",
                "reason": "Activity already exists",
            },
        ],
    }


def test_row_with_missing_filename_is_skipped_not_a_hard_failure(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    csv_content = _CSV_HEADER + _csv_row("111", "Sep 9, 2026, 8:58:03 PM", "Run", "Run", "")
    archive = _build_export_zip(csv_content, {})
    response = app_client.post(
        "/api/v1/activities/import/strava",
        headers=auth_headers,
        files={"archive": ("strava_export.zip", archive, "application/zip")},
    )
    body = response.json()
    assert body["failed"] == 1
    assert "No activity file" in body["items"][0]["reason"]


def test_gps_less_activity_is_skipped_not_failed(app_client, auth_headers) -> None:
    """A FIT file with no positioned records (a genuinely GPS-less indoor or
    virtual activity, e.g. a trainer ride) has nothing SAT can import — that
    is a normal, expected skip, not an error, so it must not land in the
    "failed" bucket alongside a truly corrupt/unparseable file."""
    no_points_fit = (_FIXTURE_DIR / "sample_no_points.fit").read_bytes()
    csv_content = _CSV_HEADER + _csv_row(
        "111", "Sep 9, 2026, 8:58:03 PM", "Indoor Ride", "Virtual Ride", "activities/111.fit.gz"
    )
    archive = _build_export_zip(
        csv_content, {"activities/111.fit.gz": gzip.compress(no_points_fit)}
    )
    response = app_client.post(
        "/api/v1/activities/import/strava",
        headers=auth_headers,
        files={"archive": ("strava_export.zip", archive, "application/zip")},
    )
    body = response.json()
    assert body["imported"] == 0
    assert body["skipped"] == 1
    assert body["failed"] == 0
    assert "No GPS track data" in body["items"][0]["reason"]


def test_one_bad_row_does_not_abort_the_whole_batch(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    csv_content = (
        _CSV_HEADER
        + _csv_row("111", "Sep 9, 2026, 8:58:03 PM", "Good Run", "Run", "activities/111.gpx.gz")
        + _csv_row(
            "222", "Sep 8, 2026, 5:09:03 PM", "Corrupt Ride", "Ride", "activities/222.fit.gz"
        )
    )
    archive = _build_export_zip(
        csv_content,
        {
            "activities/111.gpx.gz": gzip.compress(sample_gpx_bytes),
            "activities/222.fit.gz": b"not a real fit file",
        },
    )
    response = app_client.post(
        "/api/v1/activities/import/strava",
        headers=auth_headers,
        files={"archive": ("strava_export.zip", archive, "application/zip")},
    )
    body = response.json()
    assert body["imported"] == 1
    assert body["failed"] == 1
    statuses = {item["client_activity_id"]: item["status"] for item in body["items"]}
    assert statuses["strava:111"] == "imported"
    assert statuses["strava:222"] == "failed"


def test_missing_activities_csv_is_a_400(app_client, auth_headers) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("profile.csv", "irrelevant")
    response = app_client.post(
        "/api/v1/activities/import/strava",
        headers=auth_headers,
        files={"archive": ("strava_export.zip", buf.getvalue(), "application/zip")},
    )
    assert response.status_code == 400


def test_not_a_zip_is_a_400(app_client, auth_headers) -> None:
    response = app_client.post(
        "/api/v1/activities/import/strava",
        headers=auth_headers,
        files={"archive": ("strava_export.zip", b"not a zip", "application/zip")},
    )
    assert response.status_code == 400


def test_oversized_archive_is_413_with_trim_guidance(app_client, auth_headers, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setenv("SR_MAX_STRAVA_IMPORT_BYTES", "10")
    get_settings.cache_clear()
    try:
        response = app_client.post(
            "/api/v1/activities/import/strava",
            headers=auth_headers,
            files={"archive": ("strava_export.zip", b"x" * 100, "application/zip")},
        )
        assert response.status_code == 413
        assert "activities.csv" in response.json()["error"]["message"]
        assert "activities/" in response.json()["error"]["message"]
    finally:
        get_settings.cache_clear()


def test_import_is_scoped_per_user(app_client, auth_headers, sample_gpx_bytes) -> None:
    archive = _default_export(sample_gpx_bytes)
    app_client.post(
        "/api/v1/activities/import/strava",
        headers=auth_headers,
        files={"archive": ("strava_export.zip", archive, "application/zip")},
    )
    other_headers = _other_user_headers(app_client)
    other_activities = app_client.get("/api/v1/activities", headers=other_headers).json()[
        "activities"
    ]
    assert other_activities == []


def test_web_import_route_requires_htmx_header(app_client, sample_gpx_bytes) -> None:
    from app.auth.passwords import hash_password
    from app.db import get_session_factory
    from app.models.user import User
    from app.repositories.users import SqlAlchemyUserRepository

    with get_session_factory()() as session:
        now = datetime.now(UTC)
        user = User(
            email="web@example.com",
            password_hash=hash_password("web-password-123"),
            display_name="Web",
            is_admin=False,
            sessions_invalidated_at=now,
            created_at=now,
        )
        SqlAlchemyUserRepository(session).add(user)
        session.commit()

    login = app_client.post(
        "/login",
        data={"email": "web@example.com", "password": "web-password-123"},
        headers={"X-Requested-With": "htmx"},
    )
    assert login.status_code in (200, 303)

    archive = _default_export(sample_gpx_bytes)
    no_csrf = app_client.post(
        "/import/strava", files={"archive": ("strava_export.zip", archive, "application/zip")}
    )
    assert no_csrf.status_code == 403

    ok = app_client.post(
        "/import/strava",
        files={"archive": ("strava_export.zip", archive, "application/zip")},
        headers={"X-Requested-With": "htmx"},
    )
    assert ok.status_code == 200
    assert "Processing" in ok.text
    assert 'hx-trigger="every 2s"' in ok.text

    job_id = ok.text.split("/import/strava/")[1].split("/status")[0]
    status = app_client.get(f"/import/strava/{job_id}/status")
    assert status.status_code == 200
    assert "Imported 3" in status.text


def test_web_import_shows_upload_result_on_error(app_client) -> None:
    from app.auth.passwords import hash_password
    from app.db import get_session_factory
    from app.models.user import User
    from app.repositories.users import SqlAlchemyUserRepository

    with get_session_factory()() as session:
        now = datetime.now(UTC)
        user = User(
            email="web2@example.com",
            password_hash=hash_password("web-password-123"),
            display_name="Web",
            is_admin=False,
            sessions_invalidated_at=now,
            created_at=now,
        )
        SqlAlchemyUserRepository(session).add(user)
        session.commit()

    app_client.post(
        "/login",
        data={"email": "web2@example.com", "password": "web-password-123"},
        headers={"X-Requested-With": "htmx"},
    )
    response = app_client.post(
        "/import/strava",
        files={"archive": ("strava_export.zip", b"not a zip", "application/zip")},
        headers={"X-Requested-With": "htmx"},
    )
    assert response.status_code == 400
    assert "error-banner" in response.text


def _login_web_user(app_client, email: str) -> None:
    from app.auth.passwords import hash_password
    from app.db import get_session_factory
    from app.models.user import User
    from app.repositories.users import SqlAlchemyUserRepository

    with get_session_factory()() as session:
        now = datetime.now(UTC)
        user = User(
            email=email,
            password_hash=hash_password("web-password-123"),
            display_name="Web",
            is_admin=False,
            sessions_invalidated_at=now,
            created_at=now,
        )
        SqlAlchemyUserRepository(session).add(user)
        session.commit()

    login = app_client.post(
        "/login",
        data={"email": email, "password": "web-password-123"},
        headers={"X-Requested-With": "htmx"},
    )
    assert login.status_code in (200, 303)


def test_web_import_status_shows_progress_then_final_result(app_client, sample_gpx_bytes) -> None:
    """End-to-end: POST /import/strava returns a polling progress fragment
    (not the finished result, unlike the old synchronous route), and
    GET .../status reflects the completed job once the background task has
    run. TestClient runs BackgroundTasks to completion before .post()
    returns (starlette/fastapi's own documented test behaviour), so the job
    is already "done" by the time this polls — a real browser would instead
    see one or more "Processing…" responses first."""
    _login_web_user(app_client, "web-progress@example.com")
    archive = _default_export(sample_gpx_bytes)

    started = app_client.post(
        "/import/strava",
        files={"archive": ("strava_export.zip", archive, "application/zip")},
        headers={"X-Requested-With": "htmx"},
    )
    assert started.status_code == 200
    assert "Processing… 0 / 3" in started.text

    job_id = started.text.split("/import/strava/")[1].split("/status")[0]
    status = app_client.get(f"/import/strava/{job_id}/status")
    assert status.status_code == 200
    assert "Imported 3" in status.text
    # The terminal fragment must not carry its own polling trigger, or
    # polling would never stop.
    assert "hx-trigger" not in status.text


def test_web_import_status_unknown_job_id_is_a_friendly_404(app_client) -> None:
    _login_web_user(app_client, "web-unknown-job@example.com")
    response = app_client.get("/import/strava/does-not-exist/status")
    assert response.status_code == 404
    assert "error-banner" in response.text


def test_web_import_status_is_scoped_per_user(app_client, sample_gpx_bytes) -> None:
    """A signed-in user must not be able to poll another user's import job
    id and see their results — mirrors the per-user scoping already covered
    for activities themselves (test_import_is_scoped_per_user above)."""
    _login_web_user(app_client, "web-owner@example.com")
    archive = _default_export(sample_gpx_bytes)
    started = app_client.post(
        "/import/strava",
        files={"archive": ("strava_export.zip", archive, "application/zip")},
        headers={"X-Requested-With": "htmx"},
    )
    job_id = started.text.split("/import/strava/")[1].split("/status")[0]

    app_client.post("/logout", headers={"X-Requested-With": "htmx"})
    _login_web_user(app_client, "web-other-viewer@example.com")
    response = app_client.get(f"/import/strava/{job_id}/status")
    assert response.status_code == 404


def test_job_registry_tracks_progress_and_terminal_states() -> None:
    """Unit-level coverage of app/activity_import_jobs.py's in-memory
    registry, independent of the HTTP layer above."""
    from app.activity_export import ImportSummary
    from app.activity_import_jobs import (
        create_job,
        get_job,
        mark_done,
        mark_error,
        mark_running,
        update_progress,
    )

    job = create_job("user-1", total=5)
    assert job.status == "pending"
    assert job.processed == 0
    assert job.total == 5
    assert get_job(job.id) is job

    mark_running(job.id)
    assert get_job(job.id).status == "running"  # type: ignore[union-attr]

    update_progress(job.id, 3, 5)
    assert get_job(job.id).processed == 3  # type: ignore[union-attr]

    summary = ImportSummary(imported=4, skipped=1, failed=0, items=[])
    mark_done(job.id, summary)
    done_job = get_job(job.id)
    assert done_job is not None
    assert done_job.status == "done"
    assert done_job.summary is summary
    assert done_job.processed == done_job.total  # snapped to total on completion

    other = create_job("user-1", total=1)
    mark_error(other.id, "boom")
    errored = get_job(other.id)
    assert errored is not None
    assert errored.status == "error"
    assert errored.error == "boom"


def test_job_registry_returns_none_for_unknown_job() -> None:
    from app.activity_import_jobs import get_job

    assert get_job("no-such-job") is None


def test_job_registry_evicts_oldest_job_once_over_capacity() -> None:
    """_MAX_JOBS caps the registry so a script hammering the endpoint can't
    leak memory forever in this single-process, no-persistence design (see
    the module docstring) — confirms eviction is FIFO, not silent unbounded
    growth."""
    from app.activity_import_jobs import _MAX_JOBS, _jobs, create_job, get_job

    first_job = create_job("user-1", total=1)
    for _ in range(_MAX_JOBS):
        create_job("user-1", total=1)

    assert len(_jobs) == _MAX_JOBS
    assert get_job(first_job.id) is None


def test_run_strava_import_calls_on_progress_after_every_row(
    app_client, admin_token, sample_gpx_bytes
) -> None:
    """run_strava_import's on_progress callback (app/activity_import_strava.py)
    is what the background-job wrapper uses to update the polled status —
    confirms it fires once per row, in order, with the correct total, and
    that omitting it (the parameter's default) still works for existing
    callers like the JSON API route and the tests above."""
    from app.activity_import_strava import (
        parse_activities_csv,
        read_strava_export_archive,
        run_strava_import,
    )
    from app.api.v1.activities import _insert_from_strava_row
    from app.db import get_session_factory

    # admin_token's user is the "admin@example.com" user bootstrapped by the
    # admin_token fixture — reuse its id so the FK-enforced inserts succeed
    # (SQLite has foreign_keys=ON, see app/db.py's _enable_sqlite_pragmas).
    from app.repositories.users import SqlAlchemyUserRepository

    with get_session_factory()() as lookup_session:
        admin_user = SqlAlchemyUserRepository(lookup_session).get_by_email("admin@example.com")
        assert admin_user is not None
        user_id = admin_user.id

    archive_bytes = _default_export(sample_gpx_bytes)
    zip_archive = read_strava_export_archive(archive_bytes)
    with zip_archive:
        csv_rows = parse_activities_csv(zip_archive.read("activities.csv"))

        calls: list[tuple[int, int]] = []
        with get_session_factory()() as session:
            summary = run_strava_import(
                session,
                user_id,
                csv_rows,
                zip_archive,
                20_000_000,
                _insert_from_strava_row,
                on_progress=lambda processed, total: calls.append((processed, total)),
            )
            session.commit()

    assert summary.imported == 3
    assert calls == [(1, 3), (2, 3), (3, 3)]
