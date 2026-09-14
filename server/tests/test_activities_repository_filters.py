"""Repository-level tests for ActivityListFilters/list_for_user_page's
filtering (issue #76) — exercises SqlAlchemyActivityRepository directly
rather than through the web route, so these focus on the SQL itself: the
count must always match the page (both derived from one filtered base
query), and text + distance filters must combine with AND."""

from app.db import get_session_factory
from app.repositories.activities import ActivityListFilters, SqlAlchemyActivityRepository
from tests.conftest import upload_sample_activity


def _upload(app_client, auth_headers, sample_gpx_bytes, n: int) -> list[str]:
    ids = []
    for i in range(n):
        upload = upload_sample_activity(
            app_client,
            auth_headers,
            sample_gpx_bytes,
            client_activity_id=f"55555555-5555-5555-5555-{i:012d}",
        )
        ids.append(upload.json()["id"])
    return ids


def _set_title_and_distance(activity_id: str, *, title: str, distance_meters: float) -> None:
    from app.models.activity import Activity
    from app.models.activity_analysis import ActivityAnalysis

    with get_session_factory()() as session:
        activity = session.get(Activity, activity_id)
        assert activity is not None
        activity.title = title
        analysis = session.get(ActivityAnalysis, activity_id)
        assert analysis is not None
        analysis.distance_meters = distance_meters
        session.commit()


def test_filtered_count_matches_the_page_returned(app_client, auth_headers, sample_gpx_bytes):
    ids = _upload(app_client, auth_headers, sample_gpx_bytes, 5)
    for i, activity_id in enumerate(ids):
        _set_title_and_distance(activity_id, title=f"Run {i}", distance_meters=float(i))

    with get_session_factory()() as session:
        repo = SqlAlchemyActivityRepository(session)
        result = repo.list_for_user_page(
            _user_id(session),
            page=1,
            per_page=20,
            sort="date",
            direction="desc",
            filters=ActivityListFilters(min_m=2.0),
        )

    assert result.total == 3  # distances 2, 3, 4
    assert len(result.activities) == 3


def test_text_and_distance_filters_combine_with_and(app_client, auth_headers, sample_gpx_bytes):
    ids = _upload(app_client, auth_headers, sample_gpx_bytes, 3)
    _set_title_and_distance(ids[0], title="Sunrise Loop", distance_meters=1.0)
    _set_title_and_distance(ids[1], title="Sunrise Loop", distance_meters=10.0)
    _set_title_and_distance(ids[2], title="Sunset Loop", distance_meters=10.0)

    with get_session_factory()() as session:
        repo = SqlAlchemyActivityRepository(session)
        result = repo.list_for_user_page(
            _user_id(session),
            page=1,
            per_page=20,
            sort="date",
            direction="desc",
            filters=ActivityListFilters(text="sunrise", min_m=5.0),
        )

    # Only ids[1] matches both the text ("Sunrise") and the distance (>=5m) —
    # ids[0] matches text but not distance, ids[2] matches distance but not text.
    assert result.total == 1
    assert result.activities[0][0].id == ids[1]


def _user_id(session) -> str:
    from app.models.user import User

    user = session.query(User).one()
    return user.id
