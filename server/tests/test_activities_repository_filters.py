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


def _set_endpoints(
    activity_id: str,
    *,
    start: tuple[float, float] | None,
    end: tuple[float, float] | None,
) -> None:
    from app.models.activity_analysis import ActivityAnalysis

    with get_session_factory()() as session:
        analysis = session.get(ActivityAnalysis, activity_id)
        assert analysis is not None
        analysis.start_lat, analysis.start_lon = start if start is not None else (None, None)
        analysis.end_lat, analysis.end_lon = end if end is not None else (None, None)
        session.commit()


# Bristol city centre — arbitrary but real-looking coordinates, chosen so
# ~300m and ~2km displacements (used below) are ordinary, unremarkable
# distances rather than edge cases near the poles or the antimeridian.
_ORIGIN = (51.4545, -2.5879)
_NEAR_300M = (51.4572, -2.5879)  # ~300m north of _ORIGIN
_FAR_2KM = (51.4725, -2.5879)  # ~2km north of _ORIGIN


def test_geo_filter_start_mode_matches_only_on_start_point(
    app_client, auth_headers, sample_gpx_bytes
):
    ids = _upload(app_client, auth_headers, sample_gpx_bytes, 2)
    # ids[0]: starts near the search point, finishes far away.
    _set_endpoints(ids[0], start=_NEAR_300M, end=_FAR_2KM)
    # ids[1]: starts far away, finishes near the search point.
    _set_endpoints(ids[1], start=_FAR_2KM, end=_NEAR_300M)

    with get_session_factory()() as session:
        repo = SqlAlchemyActivityRepository(session)
        result = repo.list_for_user_page(
            _user_id(session),
            page=1,
            per_page=20,
            sort="date",
            direction="desc",
            filters=ActivityListFilters(
                lat=_ORIGIN[0], lon=_ORIGIN[1], radius_m=500.0, geo="start"
            ),
        )

    assert [a.id for a, _ in result.activities] == [ids[0]]


def test_geo_filter_finish_mode_matches_only_on_end_point(
    app_client, auth_headers, sample_gpx_bytes
):
    ids = _upload(app_client, auth_headers, sample_gpx_bytes, 2)
    _set_endpoints(ids[0], start=_NEAR_300M, end=_FAR_2KM)
    _set_endpoints(ids[1], start=_FAR_2KM, end=_NEAR_300M)

    with get_session_factory()() as session:
        repo = SqlAlchemyActivityRepository(session)
        result = repo.list_for_user_page(
            _user_id(session),
            page=1,
            per_page=20,
            sort="date",
            direction="desc",
            filters=ActivityListFilters(
                lat=_ORIGIN[0], lon=_ORIGIN[1], radius_m=500.0, geo="finish"
            ),
        )

    assert [a.id for a, _ in result.activities] == [ids[1]]


def test_geo_filter_either_mode_matches_start_or_finish(app_client, auth_headers, sample_gpx_bytes):
    ids = _upload(app_client, auth_headers, sample_gpx_bytes, 3)
    _set_endpoints(ids[0], start=_NEAR_300M, end=_FAR_2KM)  # matches via start
    _set_endpoints(ids[1], start=_FAR_2KM, end=_NEAR_300M)  # matches via finish
    _set_endpoints(ids[2], start=_FAR_2KM, end=_FAR_2KM)  # matches neither

    with get_session_factory()() as session:
        repo = SqlAlchemyActivityRepository(session)
        result = repo.list_for_user_page(
            _user_id(session),
            page=1,
            per_page=20,
            sort="date",
            direction="desc",
            filters=ActivityListFilters(
                lat=_ORIGIN[0], lon=_ORIGIN[1], radius_m=500.0, geo="either"
            ),
        )

    assert {a.id for a, _ in result.activities} == {ids[0], ids[1]}


def test_geo_filter_both_mode_requires_start_and_finish_near(
    app_client, auth_headers, sample_gpx_bytes
):
    ids = _upload(app_client, auth_headers, sample_gpx_bytes, 2)
    _set_endpoints(ids[0], start=_NEAR_300M, end=_NEAR_300M)  # a loop: both near
    _set_endpoints(ids[1], start=_NEAR_300M, end=_FAR_2KM)  # only start near

    with get_session_factory()() as session:
        repo = SqlAlchemyActivityRepository(session)
        result = repo.list_for_user_page(
            _user_id(session),
            page=1,
            per_page=20,
            sort="date",
            direction="desc",
            filters=ActivityListFilters(lat=_ORIGIN[0], lon=_ORIGIN[1], radius_m=500.0, geo="both"),
        )

    assert [a.id for a, _ in result.activities] == [ids[0]]


def test_geo_filter_radius_excludes_and_includes_correctly(
    app_client, auth_headers, sample_gpx_bytes
):
    ids = _upload(app_client, auth_headers, sample_gpx_bytes, 1)
    _set_endpoints(ids[0], start=_NEAR_300M, end=_NEAR_300M)

    with get_session_factory()() as session:
        repo = SqlAlchemyActivityRepository(session)
        too_small = repo.list_for_user_page(
            _user_id(session),
            page=1,
            per_page=20,
            sort="date",
            direction="desc",
            filters=ActivityListFilters(
                lat=_ORIGIN[0], lon=_ORIGIN[1], radius_m=100.0, geo="start"
            ),
        )
        big_enough = repo.list_for_user_page(
            _user_id(session),
            page=1,
            per_page=20,
            sort="date",
            direction="desc",
            filters=ActivityListFilters(
                lat=_ORIGIN[0], lon=_ORIGIN[1], radius_m=500.0, geo="start"
            ),
        )

    assert too_small.total == 0
    assert big_enough.total == 1


def test_geo_filter_never_matches_null_coordinates(app_client, auth_headers, sample_gpx_bytes):
    """An activity with no analysis, a failed one, or one analyzed before
    issue #76's endpoint columns existed has null start/end — it must never
    match a location filter, regardless of radius."""
    ids = _upload(app_client, auth_headers, sample_gpx_bytes, 1)
    _set_endpoints(ids[0], start=None, end=None)

    with get_session_factory()() as session:
        repo = SqlAlchemyActivityRepository(session)
        result = repo.list_for_user_page(
            _user_id(session),
            page=1,
            per_page=20,
            sort="date",
            direction="desc",
            filters=ActivityListFilters(
                lat=_ORIGIN[0], lon=_ORIGIN[1], radius_m=100_000.0, geo="either"
            ),
        )

    assert result.total == 0


def _user_id(session) -> str:
    from app.models.user import User

    user = session.query(User).one()
    return user.id
