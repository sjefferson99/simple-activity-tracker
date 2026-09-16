"""Route-level tests for app/web/ — see docs/WEB-PLAN.md §8 W2 acceptance
criteria: render/redirect for signed-in vs signed-out, the htmx CSRF header
rule, admin 404s for non-admins, and the self/last-admin guards."""

import json
import zipfile
from datetime import datetime
from io import BytesIO

from tests.conftest import upload_sample_activity

HTMX_HEADERS = {"X-Requested-With": "htmx"}


def _login_cookie_client(app_client, email: str, password: str):
    response = app_client.post(
        "/login",
        headers=HTMX_HEADERS,
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert response.headers["hx-redirect"] == "/"
    return app_client


def test_login_page_renders(app_client):
    response = app_client.get("/login")
    assert response.status_code == 200
    assert "Sign in" in response.text


def test_root_redirects_when_signed_out(app_client):
    response = app_client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_login_without_htmx_header_is_rejected(app_client):
    response = app_client.post(
        "/login", data={"email": "admin@example.com", "password": "admin-password-123"}
    )
    assert response.status_code == 403


def test_login_success_sets_cookie_and_redirects(app_client, auth_headers):
    response = app_client.post(
        "/login",
        headers=HTMX_HEADERS,
        data={"email": "admin@example.com", "password": "admin-password-123"},
    )
    assert response.status_code == 200
    assert response.headers["hx-redirect"] == "/"
    assert "sr_session" in response.cookies


def test_login_wrong_password_shows_error(app_client):
    response = app_client.post(
        "/login",
        headers=HTMX_HEADERS,
        data={"email": "admin@example.com", "password": "wrong"},
    )
    assert response.status_code == 401
    assert "Invalid email or password" in response.text


def test_activity_list_renders_for_signed_in_user(app_client, sample_gpx_bytes, auth_headers):
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/")
    assert response.status_code == 200
    assert "km" in response.text


def test_activity_list_includes_the_map_picker(app_client, sample_gpx_bytes, auth_headers):
    """The full-page render (not the htmx fragment) must ship the map picker
    markup and the vendored Leaflet script — see partials/activity_search_form.html
    and activities_list.html's scripts block."""
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/")
    assert response.status_code == 200
    assert 'id="map-picker-toggle"' in response.text
    assert 'id="search-map"' in response.text
    assert "/static/vendor/leaflet/leaflet.js" in response.text
    assert "/static/vendor/leaflet/leaflet.css" in response.text

    # The htmx fragment (a sort/page/search response) must NOT re-render the
    # picker or re-send Leaflet — it only lives in the full page.
    fragment = app_client.get("/", headers={"HX-Request": "true"})
    assert 'id="map-picker-toggle"' not in fragment.text


def test_activity_list_shows_analyzed_distance_not_phone_summary(
    app_client, sample_gpx_bytes, auth_headers
):
    """Issue #75: the list page's distance/duration must come from the
    server's own GPX analysis, not the phone-reported client_summary — the
    upload fixture's client_summary claims exactly 3000m/900s, which differs
    slightly from what AnalyzerV1 actually computes from the GPX track."""
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/")
    assert response.status_code == 200
    assert "3.02 km" in response.text
    assert "3.00 km" not in response.text


def test_activity_list_empty_state(app_client, auth_headers):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.get("/")
    assert response.status_code == 200
    assert "No activities yet" in response.text


def test_header_shows_signed_in_user_display_name(app_client, auth_headers):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.get("/")
    assert response.status_code == 200
    assert '<span class="current-user">Admin</span>' in response.text


def test_login_page_has_favicon_link(app_client):
    response = app_client.get("/login")
    assert response.status_code == 200
    assert '<link rel="icon" href="/static/favicon.svg"' in response.text


def test_favicon_is_served(app_client):
    response = app_client.get("/static/favicon.svg")
    assert response.status_code == 200
    assert "svg" in response.headers["content-type"]


def test_activity_list_with_malformed_pagination_params_falls_back_to_defaults(
    app_client, sample_gpx_bytes, auth_headers
):
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get(
        "/", params={"per_page": "garbage", "sort": "garbage", "dir": "garbage"}
    )
    assert response.status_code == 200
    assert "km" in response.text


def test_activity_list_stale_page_number_clamps_to_last_page(
    app_client, sample_gpx_bytes, auth_headers
):
    """A bookmarked/hand-edited page number past the end (e.g. after
    activities were deleted) shouldn't render a blank page — clamp to the
    real last page, mirroring the old cursor fallback's "don't break the
    page for a human browsing" reasoning."""
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", params={"page": 99, "per_page": "20"})
    assert response.status_code == 200
    assert "km" in response.text


def _set_activity_started_at_and_distance(
    activity_id: str, started_at: str, distance_meters: float
) -> None:
    from app.db import get_session_factory
    from app.models.activity import Activity
    from app.models.activity_analysis import ActivityAnalysis

    with get_session_factory()() as session:
        activity = session.get(Activity, activity_id)
        assert activity is not None
        activity.started_at = datetime.fromisoformat(started_at)
        analysis = session.get(ActivityAnalysis, activity_id)
        assert analysis is not None
        analysis.distance_meters = distance_meters
        session.commit()


def _upload_n_activities(app_client, auth_headers, sample_gpx_bytes, n: int) -> list[str]:
    ids = []
    for i in range(n):
        upload = upload_sample_activity(
            app_client,
            auth_headers,
            sample_gpx_bytes,
            client_activity_id=f"22222222-2222-2222-2222-{i:012d}",
        )
        activity_id = upload.json()["id"]
        _set_activity_started_at_and_distance(
            activity_id, f"2026-01-{i + 1:02d}T00:00:00+00:00", float(i)
        )
        ids.append(activity_id)
    return ids


def test_activity_list_rows_per_page_20_and_100(app_client, sample_gpx_bytes, auth_headers):
    _upload_n_activities(app_client, auth_headers, sample_gpx_bytes, 25)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", params={"per_page": "20"})
    assert response.status_code == 200
    assert response.text.count("activity-list-item") == 20
    assert '<a href="/?page=2' in response.text

    response = app_client.get("/", params={"per_page": "100"})
    assert response.status_code == 200
    assert response.text.count("activity-list-item") == 25


def test_per_page_select_hx_vals_never_carries_a_stale_per_page_value(
    app_client, sample_gpx_bytes, auth_headers
):
    """Regression: the per-page <select> submits its own value via
    hx-include="this" — if its hx-vals also carried per_page (from the
    *current*, pre-change page state), htmx's hx-vals unconditionally
    overrides a same-named field the element already submits, so switching
    the dropdown to a new value would silently keep sending the old one.
    While viewing a per_page=100 page, the rendered hx-vals JSON must not
    mention per_page at all."""
    _upload_n_activities(app_client, auth_headers, sample_gpx_bytes, 5)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", params={"per_page": "100"})
    assert response.status_code == 200
    hx_vals_start = response.text.index("hx-vals='") + len("hx-vals='")
    hx_vals_end = response.text.index("'", hx_vals_start)
    hx_vals_json = response.text[hx_vals_start:hx_vals_end]
    assert "per_page" not in hx_vals_json


def test_activity_list_rows_per_page_all_shows_every_activity(
    app_client, sample_gpx_bytes, auth_headers
):
    _upload_n_activities(app_client, auth_headers, sample_gpx_bytes, 25)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", params={"per_page": "all"})
    assert response.status_code == 200
    assert response.text.count("activity-list-item") == 25
    assert "pagination" not in response.text


def test_activity_list_page_two_shows_remaining_activities(
    app_client, sample_gpx_bytes, auth_headers
):
    _upload_n_activities(app_client, auth_headers, sample_gpx_bytes, 25)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", params={"page": 2, "per_page": "20"})
    assert response.status_code == 200
    assert response.text.count("activity-list-item") == 5


def test_activity_list_sort_by_date_ascending_and_descending(
    app_client, sample_gpx_bytes, auth_headers
):
    ids = _upload_n_activities(app_client, auth_headers, sample_gpx_bytes, 3)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", params={"sort": "date", "dir": "asc"})
    assert response.status_code == 200
    positions = [response.text.index(f"/activities/{i}") for i in ids]
    assert positions == sorted(positions)

    response = app_client.get("/", params={"sort": "date", "dir": "desc"})
    assert response.status_code == 200
    positions = [response.text.index(f"/activities/{i}") for i in ids]
    assert positions == sorted(positions, reverse=True)


def test_activity_list_sort_by_distance_ascending_and_descending(
    app_client, sample_gpx_bytes, auth_headers
):
    ids = _upload_n_activities(app_client, auth_headers, sample_gpx_bytes, 3)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", params={"sort": "distance", "dir": "asc"})
    assert response.status_code == 200
    positions = [response.text.index(f"/activities/{i}") for i in ids]
    assert positions == sorted(positions)

    response = app_client.get("/", params={"sort": "distance", "dir": "desc"})
    assert response.status_code == 200
    positions = [response.text.index(f"/activities/{i}") for i in ids]
    assert positions == sorted(positions, reverse=True)


def test_activity_list_htmx_request_returns_only_the_list_region(
    app_client, sample_gpx_bytes, auth_headers
):
    """Sort/page/per-page controls target #activity-list-region — an htmx
    request from one of them gets just that fragment back (see
    app/web/activities.py), not the whole page with its upload/import/
    Strava/export cards, so a sort/page click stays cheap."""
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert 'id="activity-list-region"' in response.text
    assert 'id="upload-form"' not in response.text
    assert "<h1>Activities</h1>" not in response.text


def test_activity_list_controls_show_a_loading_indicator(
    app_client, sample_gpx_bytes, auth_headers
):
    """Sort/page/per-page requests can take a couple of seconds against a
    large activity list — every control must wire up the shared spinner
    (id="activity-list-spinner") via hx-indicator so a click gives instant
    feedback instead of looking unresponsive (feedback from manual review of
    issue #75)."""
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/")
    assert response.status_code == 200
    assert 'id="activity-list-spinner"' in response.text
    assert response.text.count('hx-indicator="#activity-list-spinner"') >= 2


def _set_title_and_notes(activity_id: str, *, title: str | None, notes: str | None) -> None:
    from app.db import get_session_factory
    from app.models.activity import Activity

    with get_session_factory()() as session:
        activity = session.get(Activity, activity_id)
        assert activity is not None
        activity.title = title
        activity.notes = notes
        session.commit()


def _add_tag(app_client, auth_headers, activity_id: str, name: str) -> None:
    response = app_client.post(
        f"/api/v1/activities/{activity_id}/tags", headers=auth_headers, json={"name": name}
    )
    assert response.status_code == 201


def test_activity_search_clear_link_has_a_loading_indicator(
    app_client, sample_gpx_bytes, auth_headers
):
    """Regression: Clear was originally a plain <a href="/"> full-page
    reload, which gave no loading feedback and looked like a dead click on
    a slow connection — it must wire up the same shared spinner every other
    list control (sort, page, per-page) already uses."""
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/")
    assert response.status_code == 200
    assert 'id="activity-search-clear"' in response.text
    assert 'hx-indicator="#activity-list-spinner"' in response.text


def test_activity_search_shows_a_match_count_when_filtered(
    app_client, sample_gpx_bytes, auth_headers
):
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    other = upload_sample_activity(
        app_client,
        auth_headers,
        sample_gpx_bytes,
        client_activity_id="66666666-6666-6666-6666-666666666666",
    )
    _set_title_and_notes(other.json()["id"], title="Sunrise Loop", notes=None)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    unfiltered = app_client.get("/")
    assert 'class="muted activity-match-count"' not in unfiltered.text  # no filter active

    response = app_client.get("/", params={"q": "sunrise"})
    assert response.status_code == 200
    assert "1 match" in response.text


def test_activity_search_match_count_pluralizes(app_client, sample_gpx_bytes, auth_headers):
    _upload_n_activities(app_client, auth_headers, sample_gpx_bytes, 3)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", params={"min_km": "0"})
    assert response.status_code == 200
    assert "3 matches" in response.text


def test_activity_search_matches_title(app_client, sample_gpx_bytes, auth_headers):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _set_title_and_notes(activity_id, title="Sunrise Loop", notes=None)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", params={"q": "sunrise"})
    assert response.status_code == 200
    assert "Sunrise Loop" in response.text


def test_activity_search_matches_notes(app_client, sample_gpx_bytes, auth_headers):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _set_title_and_notes(activity_id, title="Untitled run", notes="Felt strong on the hills")
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", params={"q": "hills"})
    assert response.status_code == 200
    assert "Untitled run" in response.text

    no_match = app_client.get("/", params={"q": "swimming"})
    assert "Untitled run" not in no_match.text
    assert "No activities match your search" in no_match.text


def test_activity_search_no_matches_state_keeps_the_search_form_and_region(
    app_client, sample_gpx_bytes, auth_headers
):
    """The "no matches" empty state must still render #activity-list-region
    (so the sort/pagination controls' htmx swap target exists) and the
    search form must stay visible/usable so the user can change or clear
    their filter — distinct from the true "no activities at all" onboarding
    state, which shows neither."""
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", params={"q": "nonexistentterm"})
    assert response.status_code == 200
    assert 'id="activity-list-region"' in response.text
    assert 'id="activity-search-form"' in response.text
    assert "No activities match your search" in response.text
    assert "No activities yet" not in response.text  # not the onboarding empty state


def test_activity_search_matches_tag_name(app_client, sample_gpx_bytes, auth_headers):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _set_title_and_notes(activity_id, title="Morning run", notes=None)
    _add_tag(app_client, auth_headers, activity_id, "Strava")
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", params={"q": "strava"})
    assert response.status_code == 200
    assert "Morning run" in response.text


def test_activity_search_does_not_match_another_users_tag(
    app_client, sample_gpx_bytes, auth_headers
):
    """Tags are per-user (uq_tags_user_id_name) — a search must never match a
    tag belonging to someone else's identically-named tag."""
    from datetime import UTC, datetime

    from app.auth.passwords import hash_password
    from app.db import get_session_factory
    from app.models.tag import Tag
    from app.models.user import User, _new_uuid
    from app.repositories.users import SqlAlchemyUserRepository

    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _set_title_and_notes(activity_id, title="Morning run", notes=None)

    with get_session_factory()() as session:
        now = datetime.now(UTC)
        other_user = User(
            email="other@example.com",
            password_hash=hash_password("other-password-123"),
            display_name="Other",
            is_admin=False,
            sessions_invalidated_at=now,
            created_at=now,
        )
        SqlAlchemyUserRepository(session).add(other_user)
        session.flush()
        session.add(Tag(id=_new_uuid(), user_id=other_user.id, name="Strava", created_at=now))
        session.commit()

    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.get("/", params={"q": "strava"})
    assert "Morning run" not in response.text
    assert "No activities match your search" in response.text


def test_activity_search_requires_every_term_to_match_something(
    app_client, sample_gpx_bytes, auth_headers
):
    """One term matching a tag and another matching the title must both be
    required — terms are ANDed at the activity level, not the column level."""
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _set_title_and_notes(activity_id, title="Morning run", notes=None)
    _add_tag(app_client, auth_headers, activity_id, "Strava")
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    both_match = app_client.get("/", params={"q": "morning strava"})
    assert "Morning run" in both_match.text

    one_missing = app_client.get("/", params={"q": "morning nonexistentterm"})
    assert "Morning run" not in one_missing.text


def test_activity_search_is_case_insensitive(app_client, sample_gpx_bytes, auth_headers):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _set_title_and_notes(activity_id, title="Sunrise Loop", notes=None)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", params={"q": "SUNRISE"})
    assert "Sunrise Loop" in response.text


def test_activity_search_escapes_like_wildcards(app_client, sample_gpx_bytes, auth_headers):
    """A search term containing a literal "%"/"_" must be treated as that
    literal character, not a SQL LIKE wildcard — otherwise a search for
    "100%" would match anything (an unescaped "%" matches any substring),
    and a bare "%"/"_" search would match every row in the list."""
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _set_title_and_notes(activity_id, title="Effort", notes="Gave it 100% today")
    other = upload_sample_activity(
        app_client,
        auth_headers,
        sample_gpx_bytes,
        client_activity_id="44444444-4444-4444-4444-444444444444",
    )
    _set_title_and_notes(other.json()["id"], title="Plain run", notes=None)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    literal_match = app_client.get("/", params={"q": "100%"})
    assert "Effort" in literal_match.text
    assert "Plain run" not in literal_match.text

    bare_wildcard = app_client.get("/", params={"q": "%"})
    assert "Effort" in bare_wildcard.text  # contains a literal %
    assert "Plain run" not in bare_wildcard.text  # doesn't — "%" isn't a real wildcard here

    bare_underscore = app_client.get("/", params={"q": "_"})
    assert "Effort" not in bare_underscore.text
    assert "Plain run" not in bare_underscore.text


def test_activity_search_ignores_query_text_past_200_chars(
    app_client, sample_gpx_bytes, auth_headers
):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _set_title_and_notes(activity_id, title="A" * 250, notes=None)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    # The 201st+ characters are dropped before the query even runs, so a
    # 250-char title still matches a query truncated to its first 200 chars.
    response = app_client.get("/", params={"q": "A" * 250})
    assert response.status_code == 200
    assert "A" * 200 in response.text


def test_activity_search_is_preserved_in_sort_and_page_links(
    app_client, sample_gpx_bytes, auth_headers
):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _set_title_and_notes(activity_id, title="Sunrise Loop", notes=None)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", params={"q": "sunrise"})
    assert response.status_code == 200
    assert "q=sunrise" in response.text


def test_activity_search_resets_to_page_one(app_client, sample_gpx_bytes, auth_headers):
    ids = _upload_n_activities(app_client, auth_headers, sample_gpx_bytes, 25)
    _set_title_and_notes(ids[-1], title="Sunrise Loop", notes=None)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    # Land on page 2, then search — the search form's hidden inputs don't
    # carry `page`, so a new search always starts back at page 1 even if the
    # user had paged forward first.
    response = app_client.get("/", params={"q": "sunrise", "per_page": "20"})
    assert response.status_code == 200
    assert "Sunrise Loop" in response.text
    assert 'aria-current="page"' not in response.text  # only 1 match: no pagination at all


def test_activity_distance_filter_min_only(app_client, sample_gpx_bytes, auth_headers):
    _upload_n_activities(app_client, auth_headers, sample_gpx_bytes, 5)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    # _upload_n_activities gives activity i a distance of i meters (0..4).
    response = app_client.get("/", params={"min_km": "0.003"})
    assert response.status_code == 200
    assert response.text.count("activity-list-item") == 2  # distances 3, 4 (in meters)


def test_activity_distance_filter_max_only(app_client, sample_gpx_bytes, auth_headers):
    _upload_n_activities(app_client, auth_headers, sample_gpx_bytes, 5)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", params={"max_km": "0.001"})
    assert response.status_code == 200
    assert response.text.count("activity-list-item") == 2  # distances 0, 1 (in meters)


def test_activity_distance_filter_min_and_max(app_client, sample_gpx_bytes, auth_headers):
    _upload_n_activities(app_client, auth_headers, sample_gpx_bytes, 5)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", params={"min_km": "0.001", "max_km": "0.003"})
    assert response.status_code == 200
    assert response.text.count("activity-list-item") == 3  # distances 1, 2, 3


def test_activity_distance_filter_boundary_is_inclusive(app_client, sample_gpx_bytes, auth_headers):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _set_activity_started_at_and_distance(activity_id, "2026-01-01T00:00:00+00:00", 5000.0)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    exact = app_client.get("/", params={"min_km": "5"})
    assert exact.status_code == 200
    assert "activity-list-item" in exact.text


def test_activity_distance_filter_treats_unanalyzed_activity_as_zero(
    app_client, sample_gpx_bytes, auth_headers
):
    """An activity with no analysis (or a failed one) has an implied distance
    of 0 — excluded by any positive min_km, included by any max_km — same as
    ActivityAnalysis.distance_meters' own default and the sort's COALESCE."""
    from app.db import get_session_factory
    from app.models.activity_analysis import ActivityAnalysis

    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    with get_session_factory()() as session:
        analysis = session.get(ActivityAnalysis, activity_id)
        assert analysis is not None
        session.delete(analysis)
        session.commit()
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    excluded = app_client.get("/", params={"min_km": "0.01"})
    assert "No activities match your search" in excluded.text

    included = app_client.get("/", params={"max_km": "1"})
    assert "activity-list-item" in included.text


def test_activity_distance_filter_min_greater_than_max_shows_notice(
    app_client, sample_gpx_bytes, auth_headers
):
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", params={"min_km": "6", "max_km": "3"})
    assert response.status_code == 200
    assert "must not be greater than" in response.text
    # The invalid filter is ignored entirely — the unfiltered list still shows.
    assert "activity-list-item" in response.text


def test_activity_distance_filter_non_numeric_shows_notice(
    app_client, sample_gpx_bytes, auth_headers
):
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", params={"min_km": "abc"})
    assert response.status_code == 200
    assert "must be a number" in response.text
    assert "activity-list-item" in response.text


def test_activity_geo_filter_out_of_range_latitude_shows_notice(
    app_client, sample_gpx_bytes, auth_headers
):
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", params={"lat": "95", "lon": "0"})
    assert response.status_code == 200
    assert "Latitude must be between" in response.text
    # The invalid geo filter is ignored entirely — the unfiltered list still shows.
    assert "activity-list-item" in response.text


def test_activity_geo_filter_non_numeric_radius_shows_notice(
    app_client, sample_gpx_bytes, auth_headers
):
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", params={"lat": "51.5", "lon": "-0.1", "radius_km": "abc"})
    assert response.status_code == 200
    assert "Search radius must be a number" in response.text


def test_activity_geo_filter_radius_out_of_range_shows_notice(
    app_client, sample_gpx_bytes, auth_headers
):
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", params={"lat": "51.5", "lon": "-0.1", "radius_km": "500"})
    assert response.status_code == 200
    assert "Search radius must be between" in response.text


def test_activity_geo_filter_lat_without_lon_shows_notice(
    app_client, sample_gpx_bytes, auth_headers
):
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/", params={"lat": "51.5"})
    assert response.status_code == 200
    assert "Latitude must be between" in response.text


def test_activity_geo_filter_params_are_preserved_in_sort_and_page_links(
    app_client, sample_gpx_bytes, auth_headers
):
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get(
        "/", params={"lat": "51.5", "lon": "-0.1", "radius_km": "2", "geo": "start"}
    )
    assert response.status_code == 200
    assert "lat=51.5" in response.text
    assert "lon=-0.1" in response.text
    assert "radius_km=2" in response.text
    assert "geo=start" in response.text


def test_activity_geo_filter_finds_activity_by_start_point(
    app_client, sample_gpx_bytes, auth_headers
):
    """End-to-end through the web route (not just the repository, which
    test_activities_repository_filters.py already covers directly) — a
    known start point set on the analysis row must be found by a search
    at that exact location, and not found by one far away."""
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]

    from app.db import get_session_factory
    from app.models.activity_analysis import ActivityAnalysis

    with get_session_factory()() as session:
        analysis = session.get(ActivityAnalysis, activity_id)
        assert analysis is not None
        analysis.start_lat = 51.5
        analysis.start_lon = -0.1
        session.commit()

    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    nearby = app_client.get(
        "/", params={"lat": "51.5", "lon": "-0.1", "radius_km": "1", "geo": "start"}
    )
    assert "activity-list-item" in nearby.text

    far_away = app_client.get(
        "/", params={"lat": "0", "lon": "0", "radius_km": "1", "geo": "start"}
    )
    assert "No activities match your search" in far_away.text


def test_activity_detail_renders_with_map_and_analysis(app_client, sample_gpx_bytes, auth_headers):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get(f"/activities/{activity_id}")
    assert response.status_code == 200
    assert 'id="map"' in response.text
    assert "Distance (server)" in response.text
    assert "Splits" in response.text


def test_activity_detail_404_for_missing_activity(app_client, auth_headers):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.get("/activities/does-not-exist")
    assert response.status_code == 404


def test_activity_detail_has_split_controls(app_client, sample_gpx_bytes, auth_headers):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get(f"/activities/{activity_id}")
    assert response.status_code == 200
    assert f'hx-get="/activities/{activity_id}/splits"' in response.text
    assert 'id="splits-table"' in response.text


def test_activity_detail_shows_split_controls_even_with_zero_completed_splits(
    app_client, sample_gpx_bytes, auth_headers
):
    """A short activity (e.g. a few seconds stationary) never crosses a
    split boundary, so result.splits is empty — the control to try a
    smaller split size must still be offered, not hidden along with the
    (empty) table."""
    from app.db import get_session_factory
    from app.models.activity_analysis import ActivityAnalysis

    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]

    with get_session_factory()() as session:
        analysis = session.get(ActivityAnalysis, activity_id)
        assert analysis is not None
        result = dict(analysis.result)
        result["splits"] = []
        analysis.result = result
        session.commit()

    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.get(f"/activities/{activity_id}")
    assert response.status_code == 200
    assert f'hx-get="/activities/{activity_id}/splits"' in response.text


def test_splits_fragment_recomputes_with_given_split(app_client, sample_gpx_bytes, auth_headers):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get(
        f"/activities/{activity_id}/splits", params={"split_type": "time_min", "split_value": 5}
    )
    assert response.status_code == 200
    assert "Splits (5 min)" in response.text


def test_splits_table_always_shows_a_speed_column(app_client, sample_gpx_bytes, auth_headers):
    """Requested alongside a target: with a target shown as pace, comparing
    it against the actual required a mental pace<->speed conversion — a
    Speed column next to Pace removes that, for every activity regardless
    of whether it has a plan."""
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get(f"/activities/{activity_id}")
    assert response.status_code == 200
    assert "<th>Speed</th>" in response.text
    assert "km/h" in response.text


def test_splits_fragment_defaults_to_one_km(app_client, sample_gpx_bytes, auth_headers):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get(f"/activities/{activity_id}/splits")
    assert response.status_code == 200
    assert "Splits (1 km)" in response.text


def test_splits_fragment_rejects_invalid_split_type(app_client, sample_gpx_bytes, auth_headers):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get(
        f"/activities/{activity_id}/splits", params={"split_type": "bogus", "split_value": 1}
    )
    assert response.status_code == 422


def test_splits_fragment_404_for_missing_activity(app_client, auth_headers):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.get("/activities/does-not-exist/splits")
    assert response.status_code == 404


_SPLIT_NS = "https://simple-activity-tracker.local/gpx-extensions"


def _gpx_with_custom_plan() -> bytes:
    """A real (timestamped, moving) track at a constant 5 m/s, long enough to
    complete a 300m custom-plan split, carrying a sat:split_plan extension —
    see tests/test_split_plan_api.py's identical fixture for the API-level
    equivalent of this helper."""
    points = []
    lon_per_meter = 1 / 111195
    for i in range(90):
        lon = i * 5.0 * lon_per_meter
        minutes, seconds = divmod(i, 60)
        points.append(
            f'<trkpt lat="0.0" lon="{lon}">'
            f"<time>2026-01-01T00:{minutes:02d}:{seconds:02d}Z</time></trkpt>"
        )
    return (
        f'<?xml version="1.0"?><gpx version="1.1" xmlns:sat="{_SPLIT_NS}">'
        "<extensions><sat:split_type>distance_km</sat:split_type>"
        "<sat:split_value>1</sat:split_value>"
        "<sat:split_plan>100@4;200@6</sat:split_plan>"
        "<sat:split_targets_as>speed</sat:split_targets_as></extensions>"
        f"<trk><trkseg>{''.join(points)}</trkseg></trk></gpx>"
    ).encode()


def test_activity_detail_shows_reset_link_only_when_activity_has_a_plan(
    app_client, sample_gpx_bytes, auth_headers
):
    from tests.conftest import make_summary

    plain_upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    plain_id = plain_upload.json()["id"]

    plan_upload = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={
            "summary": json.dumps(
                make_summary(client_activity_id="22222222-2222-2222-2222-222222222222")
            )
        },
        files={"gpx": ("plan.gpx", _gpx_with_custom_plan(), "application/gpx+xml")},
    )
    plan_id = plan_upload.json()["id"]

    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    plain_response = app_client.get(f"/activities/{plain_id}")
    assert "Reset to my uploaded plan" not in plain_response.text

    plan_response = app_client.get(f"/activities/{plan_id}")
    assert "Reset to my uploaded plan" in plan_response.text
    assert f'hx-get="/activities/{plan_id}/splits/reset"' in plan_response.text


def test_activity_detail_for_a_plain_rolling_plan_shows_its_real_size(
    app_client, sample_gpx_bytes, auth_headers
):
    """Regression guard for the custom-plan blanking below: an activity with
    no plan (or a rolling plan) must keep showing its real split size in
    both the heading and the pre-selected controls — only a custom plan
    (variable per-split sizes) should blank them."""
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get(f"/activities/{activity_id}")
    assert response.status_code == 200
    assert "Splits (1 km)" in response.text
    assert 'value="1"' in response.text
    assert 'value="distance_km" selected' in response.text


def test_activity_detail_for_a_custom_plan_shows_a_plain_heading_and_blank_controls(
    app_client, auth_headers
):
    """Issue #100 follow-up: a custom plan's splits vary in size, so
    result.split_type/split_value is only the plan's rolling *base* (used
    once the plan's own splits run out) — showing it as "Splits (1 km)" with
    "1"/"Kilometers" pre-selected falsely implies every split below is 1 km.
    """
    from tests.conftest import make_summary

    upload = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(make_summary())},
        files={"gpx": ("plan.gpx", _gpx_with_custom_plan(), "application/gpx+xml")},
    )
    activity_id = upload.json()["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get(f"/activities/{activity_id}")
    assert response.status_code == 200
    assert ">Splits<" in response.text
    assert "Splits (1 km)" not in response.text
    assert 'value=""' in response.text
    assert 'value="" selected disabled hidden' in response.text


def test_splits_reset_restores_the_uploaded_plan_after_a_reslice(app_client, auth_headers) -> None:
    from tests.conftest import make_summary

    upload = app_client.post(
        "/api/v1/activities",
        headers=auth_headers,
        data={"summary": json.dumps(make_summary())},
        files={"gpx": ("plan.gpx", _gpx_with_custom_plan(), "application/gpx+xml")},
    )
    activity_id = upload.json()["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    resliced = app_client.get(
        f"/activities/{activity_id}/splits", params={"split_type": "time_min", "split_value": 2}
    )
    assert resliced.status_code == 200
    assert "Target" not in resliced.text  # re-slicing drops the plan's targets

    reset = app_client.get(f"/activities/{activity_id}/splits/reset")
    assert reset.status_code == 200
    # A custom plan's splits vary in size, so the heading is a plain
    # "Splits" — not "Splits (1 km)", which would misstate the plan's own
    # rolling base size as if every split below were actually that size.
    assert "<h2" in reset.text
    assert ">Splits<" in reset.text
    assert "Splits (1 km)" not in reset.text
    assert "Target" in reset.text
    # Out-of-band swap puts the size controls back too, not just the table —
    # blanked out for a custom plan, for the same reason as the heading.
    assert 'id="split_value"' in reset.text
    assert 'value=""' in reset.text
    assert 'id="split_type"' in reset.text
    assert 'value="" selected disabled hidden' in reset.text


def test_splits_reset_404_for_missing_activity(app_client, auth_headers):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.get("/activities/does-not-exist/splits/reset")
    assert response.status_code == 404


def test_activity_detail_renders_pre_feature_splits_with_no_distance_field(
    app_client, sample_gpx_bytes, auth_headers
):
    """Regression: activities analyzed before this feature shipped have
    result.splits entries with no "distance_m" key at all (not null —
    genuinely absent). Jinja's dot-access returns its Undefined sentinel for
    a missing dict key, which `is none` does not catch, so the template must
    use a falsy check instead or this 500s on any real activity whose splits
    actually completed under the old code."""
    from app.db import get_session_factory
    from app.models.activity_analysis import ActivityAnalysis

    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]

    with get_session_factory()() as session:
        analysis = session.get(ActivityAnalysis, activity_id)
        assert analysis is not None
        result = dict(analysis.result)
        result.pop("split_type", None)
        result.pop("split_value", None)
        result["splits"] = [
            {
                "index": 1,
                "duration_seconds": 300.0,
                "avg_speed_mps": 3.33,
                "elevation_delta_m": 0.0,
                # deliberately no "distance_m" key
            }
        ]
        analysis.result = result
        session.commit()

    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.get(f"/activities/{activity_id}")
    assert response.status_code == 200
    assert "Splits (1 km)" in response.text
    assert "—" in response.text


def test_activity_patch_without_htmx_header_is_403(app_client, sample_gpx_bytes, auth_headers):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.patch(f"/activities/{activity_id}", data={"title": "Morning run"})
    assert response.status_code == 403


def test_activity_patch_updates_title_and_notes(app_client, sample_gpx_bytes, auth_headers):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.patch(
        f"/activities/{activity_id}",
        headers=HTMX_HEADERS,
        data={"title": "Morning run", "notes": "Felt good"},
    )
    assert response.status_code == 200
    assert response.headers.get("hx-refresh") == "true"

    check = app_client.get(f"/api/v1/activities/{activity_id}", headers=auth_headers)
    assert check.json()["title"] == "Morning run"
    assert check.json()["notes"] == "Felt good"


def test_activity_patch_rejects_oversized_title(app_client, sample_gpx_bytes, auth_headers):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.patch(
        f"/activities/{activity_id}",
        headers=HTMX_HEADERS,
        data={"title": "x" * 100_000, "notes": ""},
    )
    assert response.status_code == 400

    check = app_client.get(f"/api/v1/activities/{activity_id}", headers=auth_headers)
    assert check.json()["title"] is None


def test_activity_delete_via_web_removes_activity(app_client, sample_gpx_bytes, auth_headers):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.delete(f"/activities/{activity_id}", headers=HTMX_HEADERS)
    assert response.status_code == 200
    assert response.headers.get("hx-redirect") == "/"

    check = app_client.get(f"/api/v1/activities/{activity_id}", headers=auth_headers)
    assert check.status_code == 404


def test_bulk_delete_removes_only_selected_activities(app_client, sample_gpx_bytes, auth_headers):
    first = upload_sample_activity(
        app_client, auth_headers, sample_gpx_bytes, "cccccccc-cccc-cccc-cccc-cccccccccccc"
    ).json()
    second = upload_sample_activity(
        app_client, auth_headers, sample_gpx_bytes, "dddddddd-dddd-dddd-dddd-dddddddddddd"
    ).json()
    kept = upload_sample_activity(
        app_client, auth_headers, sample_gpx_bytes, "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    ).json()
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.post(
        "/activities/bulk-delete",
        headers=HTMX_HEADERS,
        data={"activity_ids": [first["id"], second["id"]]},
    )
    assert response.status_code == 200
    assert response.headers.get("hx-redirect") == "/"

    assert (
        app_client.get(f"/api/v1/activities/{first['id']}", headers=auth_headers).status_code == 404
    )
    assert (
        app_client.get(f"/api/v1/activities/{second['id']}", headers=auth_headers).status_code
        == 404
    )
    assert (
        app_client.get(f"/api/v1/activities/{kept['id']}", headers=auth_headers).status_code == 200
    )


def test_bulk_delete_with_no_selection_is_400(app_client, sample_gpx_bytes, auth_headers):
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.post("/activities/bulk-delete", headers=HTMX_HEADERS, data={})
    assert response.status_code == 400


def test_bulk_delete_with_only_stale_ids_is_400(app_client, sample_gpx_bytes, auth_headers):
    """A page open in another tab may have already deleted every selected
    activity by the time this request lands — that must not look identical
    to a successful bulk delete (a silent 200 would give no signal that
    nothing was actually removed)."""
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.post(
        "/activities/bulk-delete",
        headers=HTMX_HEADERS,
        data={"activity_ids": ["does-not-exist", "also-does-not-exist"]},
    )
    assert response.status_code == 400


def test_bulk_delete_ignores_unknown_and_foreign_ids(app_client, sample_gpx_bytes, auth_headers):
    from tests.test_strava_import import _other_user_headers

    own = upload_sample_activity(
        app_client, auth_headers, sample_gpx_bytes, "ffffffff-ffff-ffff-ffff-ffffffffffff"
    ).json()
    other_headers = _other_user_headers(app_client)
    foreign = upload_sample_activity(
        app_client, other_headers, sample_gpx_bytes, "11111111-2222-3333-4444-555555555555"
    ).json()
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.post(
        "/activities/bulk-delete",
        headers=HTMX_HEADERS,
        data={"activity_ids": [own["id"], foreign["id"], "does-not-exist"]},
    )
    assert response.status_code == 200

    assert (
        app_client.get(f"/api/v1/activities/{own['id']}", headers=auth_headers).status_code == 404
    )
    # The foreign activity (owned by a different user) must survive untouched.
    assert (
        app_client.get(f"/api/v1/activities/{foreign['id']}", headers=other_headers).status_code
        == 200
    )


def test_bulk_delete_requires_htmx_header(app_client, sample_gpx_bytes, auth_headers):
    upload = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    activity_id = upload.json()["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.post("/activities/bulk-delete", data={"activity_ids": [activity_id]})
    assert response.status_code == 403


def test_web_export_all_does_not_require_htmx_header(app_client, sample_gpx_bytes, auth_headers):
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/export")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"


def test_web_export_selected_ids(app_client, sample_gpx_bytes, auth_headers):
    first = upload_sample_activity(
        app_client, auth_headers, sample_gpx_bytes, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    ).json()
    upload_sample_activity(
        app_client, auth_headers, sample_gpx_bytes, "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    )
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/export", params={"activity_ids": [first["id"]], "selection": "1"})
    assert response.status_code == 200
    archive = zipfile.ZipFile(BytesIO(response.content))
    manifest = json.loads(archive.read("manifest.json"))
    assert len(manifest["activities"]) == 1


def test_web_export_selected_with_nothing_checked_is_rejected_not_export_all(
    app_client, sample_gpx_bytes, auth_headers
):
    """Regression test: the 'Export selected' button submits #export-form
    (activities_list.html) via GET with no activity_ids at all when every
    checkbox is unchecked (unchecked checkboxes are never submitted) — the
    same wire shape as the plain 'Export all' link. The hidden `selection=1`
    field is what lets the route tell these two cases apart; without it, an
    empty selection silently exported everything instead of erroring."""
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/export", params={"selection": "1"})
    assert response.status_code == 400


def test_web_export_without_selection_marker_exports_all(
    app_client, sample_gpx_bytes, auth_headers
):
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/export")
    assert response.status_code == 200
    archive = zipfile.ZipFile(BytesIO(response.content))
    manifest = json.loads(archive.read("manifest.json"))
    assert len(manifest["activities"]) == 1


def test_web_export_filtered_by_text_query(app_client, sample_gpx_bytes, auth_headers):
    matching = upload_sample_activity(
        app_client, auth_headers, sample_gpx_bytes, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    ).json()
    non_matching = upload_sample_activity(
        app_client, auth_headers, sample_gpx_bytes, "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    ).json()
    _set_title_and_notes(matching["id"], title="Sunrise Loop", notes=None)
    _set_title_and_notes(non_matching["id"], title="Evening Jog", notes=None)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/export/filtered", params={"q": "sunrise"})
    assert response.status_code == 200
    archive = zipfile.ZipFile(BytesIO(response.content))
    manifest = json.loads(archive.read("manifest.json"))
    assert len(manifest["activities"]) == 1
    assert manifest["activities"][0]["client_activity_id"] == matching["client_activity_id"]


def test_web_export_filtered_by_distance(app_client, sample_gpx_bytes, auth_headers):
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    # The sample fixture's analyzed distance is well under 5km (see
    # test_activity_distance_filter_boundary_is_inclusive), so a 5km minimum
    # excludes it entirely.
    response = app_client.get("/export/filtered", params={"min_km": "5"})
    assert response.status_code == 200
    archive = zipfile.ZipFile(BytesIO(response.content))
    manifest = json.loads(archive.read("manifest.json"))
    assert len(manifest["activities"]) == 0


def test_web_export_filtered_no_filter_exports_everything(
    app_client, sample_gpx_bytes, auth_headers
):
    upload_sample_activity(
        app_client, auth_headers, sample_gpx_bytes, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    )
    upload_sample_activity(
        app_client, auth_headers, sample_gpx_bytes, "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    )
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/export/filtered")
    assert response.status_code == 200
    archive = zipfile.ZipFile(BytesIO(response.content))
    manifest = json.loads(archive.read("manifest.json"))
    assert len(manifest["activities"]) == 2


def test_web_export_filtered_does_not_require_htmx_header(
    app_client, sample_gpx_bytes, auth_headers
):
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/export/filtered", params={"q": "anything"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"


def test_activities_list_page_shows_export_filtered_link_only_when_filtered(
    app_client, sample_gpx_bytes, auth_headers
):
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    unfiltered = app_client.get("/")
    assert 'href="/export/filtered' not in unfiltered.text

    filtered = app_client.get("/", params={"q": "anything"})
    assert 'href="/export/filtered?q=anything"' in filtered.text


def test_activities_list_page_has_export_and_import_controls(
    app_client, sample_gpx_bytes, auth_headers
):
    upload_sample_activity(app_client, auth_headers, sample_gpx_bytes)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get("/")
    assert response.status_code == 200
    assert 'href="/export"' in response.text
    assert 'hx-post="/import"' in response.text
    assert 'name="activity_ids"' in response.text


def test_web_import_requires_htmx_header(app_client, auth_headers):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.post(
        "/import", files={"archive": ("export.zip", b"x", "application/zip")}
    )
    assert response.status_code == 403


def test_web_import_round_trip(app_client, sample_gpx_bytes, auth_headers):
    original = upload_sample_activity(app_client, auth_headers, sample_gpx_bytes).json()
    app_client.delete(f"/api/v1/activities/{original['id']}", headers=auth_headers)

    manifest = {
        "activities": [
            {
                "client_activity_id": original["client_activity_id"],
                "activity_type": original["activity_type"],
                "started_at": original["started_at"],
                "ended_at": original["ended_at"],
                "title": original["title"],
                "notes": original["notes"],
                "client_summary": original["client_summary"],
                "source_platform": original["source_platform"],
                "source_app_version": original["source_app_version"],
                "gpx_filename": f"{original['client_activity_id']}.gpx",
            }
        ]
    }
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr(f"{original['client_activity_id']}.gpx", sample_gpx_bytes)

    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.post(
        "/import",
        headers=HTMX_HEADERS,
        files={"archive": ("export.zip", buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 200
    assert "Imported 1" in response.text

    listing = app_client.get("/api/v1/activities", headers=auth_headers).json()
    assert len(listing["activities"]) == 1


def test_devices_page_lists_bearer_device(app_client, auth_headers):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.get("/devices")
    assert response.status_code == 200
    assert "test" in response.text  # the admin_token fixture's device_name


def test_device_revoke_without_htmx_header_is_403(app_client, auth_headers):
    devices = app_client.get("/api/v1/me/devices", headers=auth_headers).json()
    device_id = devices[0]["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.delete(f"/devices/{device_id}")
    assert response.status_code == 403


def test_device_revoke_via_web(app_client, auth_headers):
    devices = app_client.get("/api/v1/me/devices", headers=auth_headers).json()
    device_id = devices[0]["id"]
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.delete(f"/devices/{device_id}", headers=HTMX_HEADERS)
    assert response.status_code == 200

    check = app_client.get("/api/v1/me/devices", headers=auth_headers)
    assert check.status_code == 401  # the presenting bearer token was just revoked


def test_settings_page_renders(app_client, auth_headers):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.get("/settings")
    assert response.status_code == 200
    assert "Change password" in response.text


def test_change_password_wrong_current_password(app_client, auth_headers):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.put(
        "/settings/password",
        headers=HTMX_HEADERS,
        data={"current_password": "wrong", "new_password": "new-password-123"},
    )
    assert response.status_code == 401
    assert "incorrect" in response.text


def test_change_password_success_keeps_current_session(app_client, auth_headers):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.put(
        "/settings/password",
        headers=HTMX_HEADERS,
        data={"current_password": "admin-password-123", "new_password": "new-password-123"},
    )
    assert response.status_code == 200
    assert "sr_session" in response.cookies  # re-minted, so this browser stays signed in

    # The bearer token used to log in this fixture's admin should now be revoked.
    check = app_client.get("/api/v1/me", headers=auth_headers)
    assert check.status_code == 401

    still_in = app_client.get("/settings")
    assert still_in.status_code == 200


def test_register_disabled_by_default_returns_404(app_client):
    response = app_client.get("/register")
    assert response.status_code == 404


def test_register_when_enabled(app_client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("SR_ALLOW_REGISTRATION", "true")
    get_settings.cache_clear()
    try:
        page = app_client.get("/register")
        assert page.status_code == 200

        response = app_client.post(
            "/register",
            headers=HTMX_HEADERS,
            data={
                "display_name": "New User",
                "email": "newuser@example.com",
                "password": "password123",
            },
        )
        assert response.status_code == 200
        assert response.headers["hx-redirect"] == "/"
        assert "sr_session" in response.cookies
    finally:
        get_settings.cache_clear()


def test_register_rejects_short_password_and_invalid_email(app_client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("SR_ALLOW_REGISTRATION", "true")
    get_settings.cache_clear()
    try:
        response = app_client.post(
            "/register",
            headers=HTMX_HEADERS,
            data={
                "display_name": "New User",
                "email": "not-an-email",
                "password": "x",
            },
        )
        assert response.status_code == 400
        assert "sr_session" not in response.cookies
    finally:
        get_settings.cache_clear()


def test_admin_users_page_404_for_non_admin(app_client, auth_headers):
    # Create a non-admin user directly via the admin API, then sign in as them.
    create = app_client.post(
        "/api/v1/admin/users",
        headers=auth_headers,
        json={
            "email": "member@example.com",
            "display_name": "Member",
            "password": "member-password-123",
        },
    )
    assert create.status_code == 201

    _login_cookie_client(app_client, "member@example.com", "member-password-123")
    response = app_client.get("/admin/users")
    assert response.status_code == 404


def test_admin_users_page_renders_for_admin(app_client, auth_headers):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.get("/admin/users")
    assert response.status_code == 200
    assert "admin@example.com" in response.text


def test_admin_cannot_demote_self(app_client, auth_headers):
    client = _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    admin_id = client.get("/api/v1/me").json()["id"]

    response = client.patch(
        f"/admin/users/{admin_id}", headers=HTMX_HEADERS, data={"is_admin": "false"}
    )
    assert response.status_code == 400
    assert "cannot demote or disable your own account" in response.text


def test_admin_cannot_delete_last_admin_via_other_admin(app_client, auth_headers):
    # Promote a second user to admin, then have the ORIGINAL admin try to
    # demote themself while the other admin exists — should succeed, since
    # there'd still be one enabled admin left (the other user). Then, with
    # only one admin left, demoting/disabling that one should be blocked.
    create = app_client.post(
        "/api/v1/admin/users",
        headers=auth_headers,
        json={
            "email": "second-admin@example.com",
            "display_name": "Second Admin",
            "password": "second-password-123",
            "is_admin": True,
        },
    )
    assert create.status_code == 201
    second_admin_id = create.json()["id"]

    client = _login_cookie_client(app_client, "second-admin@example.com", "second-password-123")
    response = client.patch(
        f"/admin/users/{second_admin_id}", headers=HTMX_HEADERS, data={"is_admin": "false"}
    )
    assert response.status_code == 400
    assert "cannot demote or disable your own account" in response.text


def test_disabling_user_kills_session_and_device_token(app_client, auth_headers):
    create = app_client.post(
        "/api/v1/admin/users",
        headers=auth_headers,
        json={
            "email": "member2@example.com",
            "display_name": "Member2",
            "password": "member2-password-123",
        },
    )
    member_id = create.json()["id"]

    member_login = app_client.post(
        "/api/v1/auth/login",
        json={
            "email": "member2@example.com",
            "password": "member2-password-123",
            "device_name": "member-phone",
        },
    )
    member_headers = {"Authorization": f"Bearer {member_login.json()['token']}"}

    # Capture the member's own session cookie value before the admin (who
    # shares this same TestClient/cookie jar) signs in and overwrites it.
    _login_cookie_client(app_client, "member2@example.com", "member2-password-123")
    member_cookie = app_client.cookies.get("sr_session")
    assert member_cookie is not None

    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    disable = app_client.patch(
        f"/admin/users/{member_id}", headers=HTMX_HEADERS, data={"disabled": "true"}
    )
    assert disable.status_code == 200

    assert app_client.get("/api/v1/me", headers=member_headers).status_code == 401

    # Set the Cookie header directly rather than TestClient's per-request
    # cookies= (deprecated) — this overrides the jar's current (admin)
    # cookie for this one request without mutating the shared jar.
    stale_session_check = app_client.get(
        "/", headers={"Cookie": f"sr_session={member_cookie}"}, follow_redirects=False
    )
    assert stale_session_check.status_code == 303


def _create_member(
    app_client, auth_headers, email="member3@example.com", password="member3-password-123"
):
    response = app_client.post(
        "/api/v1/admin/users",
        headers=auth_headers,
        json={"email": email, "display_name": "Member", "password": password},
    )
    assert response.status_code == 201
    return response.json()


def test_admin_password_form_renders_inline(app_client, auth_headers):
    member = _create_member(app_client, auth_headers)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get(f"/admin/users/{member['id']}/password-form")
    assert response.status_code == 200
    assert f"admin-user-row-{member['id']}" in response.text
    assert 'name="new_password"' in response.text


def test_admin_password_form_cancel_restores_the_row(app_client, auth_headers):
    member = _create_member(app_client, auth_headers)
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.get(f"/admin/users/{member['id']}/password-form/cancel")
    assert response.status_code == 200
    assert "Reset password" in response.text
    assert 'name="new_password"' not in response.text


def test_admin_reset_password_via_inline_form_updates_the_password(app_client, auth_headers):
    member = _create_member(app_client, auth_headers, "member4@example.com", "member4-password-123")
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.post(
        f"/admin/users/{member['id']}/password",
        headers=HTMX_HEADERS,
        data={"new_password": "a-brand-new-password"},
    )
    assert response.status_code == 200
    assert member["email"] in response.text

    login = app_client.post(
        "/api/v1/auth/login",
        json={
            "email": "member4@example.com",
            "password": "a-brand-new-password",
            "device_name": "x",
        },
    )
    assert login.status_code == 200


def test_admin_reset_password_via_inline_form_rejects_short_password(app_client, auth_headers):
    member = _create_member(app_client, auth_headers, "member5@example.com", "member5-password-123")
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.post(
        f"/admin/users/{member['id']}/password",
        headers=HTMX_HEADERS,
        data={"new_password": "short"},
    )
    assert response.status_code == 400
    assert f"admin-user-row-{member['id']}" in response.text
    assert 'name="new_password"' in response.text


def test_admin_password_form_without_htmx_header_is_403(app_client, auth_headers):
    member = _create_member(app_client, auth_headers, "member6@example.com", "member6-password-123")
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")

    response = app_client.post(
        f"/admin/users/{member['id']}/password", data={"new_password": "a-brand-new-password"}
    )
    assert response.status_code == 403
