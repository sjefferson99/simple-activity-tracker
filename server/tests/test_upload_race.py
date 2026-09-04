from datetime import UTC, datetime

from app.config import get_settings
from app.db import get_session_factory
from app.models.activity import Activity
from app.repositories.activities import SqlAlchemyActivityRepository
from tests.conftest import make_summary, upload_sample_activity


def _insert_directly(user_id: str, client_activity_id: str, activity_id: str) -> None:
    """Inserts an Activity row via its own independent session/commit — used
    to simulate "another request's transaction landed first" without
    fighting SQLite's single-writer semantics inside one still-open
    transaction (see the route's own IntegrityError handling in
    app/api/v1/activities.py, which is what actually runs this same race
    against a genuinely concurrent second request in production)."""
    summary_dict = make_summary(client_activity_id)
    now = datetime.now(UTC)
    started_at = datetime.fromisoformat(summary_dict["started_at"].replace("Z", "+00:00"))
    ended_at = datetime.fromisoformat(summary_dict["ended_at"].replace("Z", "+00:00"))
    with get_session_factory()() as session:
        session.add(
            Activity(
                id=activity_id,
                user_id=user_id,
                client_activity_id=client_activity_id,
                activity_type="running",
                started_at=started_at,
                ended_at=ended_at,
                client_summary=summary_dict,
                gpx_blob_key=f"{user_id}/winner.gpx",
                gpx_sha256="0" * 64,
                gpx_bytes=1,
                source_platform="android",
                source_app_version="1.0.0+1",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def test_concurrent_insert_of_same_client_activity_id_is_recovered_not_a_500(
    app_client, auth_headers
) -> None:
    """Exercises the IntegrityError recovery path directly against the real
    engine/session machinery: two SqlAlchemyActivityRepository.add() calls
    for the same (user_id, client_activity_id) racing to flush, exactly as
    upload_activity() does around its own session.begin_nested() (see R3 in
    docs/SERVER-PRODUCTION-PLAN.md). The second flush must hit
    uq_activities_user_client_activity_id, be caught, and — after an
    explicit session.rollback() — leave the session usable for the
    subsequent lookup, exactly as the route's except clause does.
    """
    from sqlalchemy.exc import IntegrityError

    # Ensure the settings/engine this test uses are the ones app_client set up.
    get_settings()

    # Discover the real admin user id via the API rather than reaching into
    # the DB with a guessed id.
    me = app_client.get("/api/v1/me", headers=auth_headers)
    assert me.status_code == 200
    user_id = me.json()["id"]

    client_activity_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    _insert_directly(user_id, client_activity_id, activity_id="winner-id")

    with get_session_factory()() as session:
        repo = SqlAlchemyActivityRepository(session)
        summary_dict = make_summary(client_activity_id)
        now = datetime.now(UTC)
        loser = Activity(
            id="loser-id",
            user_id=user_id,
            client_activity_id=client_activity_id,
            activity_type="running",
            started_at=datetime.fromisoformat(summary_dict["started_at"].replace("Z", "+00:00")),
            ended_at=datetime.fromisoformat(summary_dict["ended_at"].replace("Z", "+00:00")),
            client_summary=summary_dict,
            gpx_blob_key=f"{user_id}/loser.gpx",
            gpx_sha256="1" * 64,
            gpx_bytes=1,
            source_platform="android",
            source_app_version="1.0.0+1",
            created_at=now,
            updated_at=now,
        )
        repo.add(loser)

        raised = False
        try:
            with session.begin_nested():
                session.flush()
        except IntegrityError:
            raised = True
            # begin_nested() only unwinds the SAVEPOINT; the Session is left
            # needing an explicit rollback() before it's usable again — this
            # is the fix in app/api/v1/activities.py's own except clause.
            session.rollback()

        assert raised, "expected the duplicate insert to raise IntegrityError"

        winner = repo.get_by_client_activity_id(user_id, client_activity_id)
        assert winner is not None
        assert winner.id == "winner-id"
        session.commit()


def test_full_upload_endpoint_still_works_normally(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    """Regression check that the begin_nested() guard added for R3 doesn't
    change behavior on the non-racing path."""
    response = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    assert response.status_code == 201


def test_different_client_activity_ids_are_unaffected_by_the_race_guard(
    app_client, auth_headers, sample_gpx_bytes
) -> None:
    first = upload_sample_activity(
        app_client, auth_headers, sample_gpx_bytes, "dddddddd-dddd-dddd-dddd-dddddddddddd"
    )
    second = upload_sample_activity(
        app_client, auth_headers, sample_gpx_bytes, "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    )
    assert first.status_code == 201
    assert second.status_code == 201
