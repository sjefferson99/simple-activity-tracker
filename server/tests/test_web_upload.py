"""Web GPX upload without the mobile app (issue #38)."""

from pathlib import Path

from tests.test_web_pages import HTMX_HEADERS, _login_cookie_client

_FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_upload_requires_htmx_header(app_client, auth_headers, sample_gpx_bytes):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.post(
        "/upload", files={"gpx": ("activity.gpx", sample_gpx_bytes, "application/gpx+xml")}
    )
    assert response.status_code == 403


def test_upload_creates_activity_and_redirects(app_client, auth_headers, sample_gpx_bytes):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.post(
        "/upload",
        headers=HTMX_HEADERS,
        data={"activity_type": "cycling"},
        files={"gpx": ("activity.gpx", sample_gpx_bytes, "application/gpx+xml")},
    )
    assert response.status_code == 200
    redirect = response.headers["hx-redirect"]
    assert redirect.startswith("/activities/")

    detail = app_client.get(redirect)
    assert detail.status_code == 200
    assert "Uploaded manually" in detail.text
    assert "Cycle" in detail.text


def test_upload_defaults_to_running(app_client, auth_headers, sample_gpx_bytes):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.post(
        "/upload",
        headers=HTMX_HEADERS,
        files={"gpx": ("activity.gpx", sample_gpx_bytes, "application/gpx+xml")},
    )
    assert response.status_code == 200
    detail = app_client.get(response.headers["hx-redirect"])
    assert "Run" in detail.text


def test_upload_guesses_device_name_from_gpx_creator(app_client, auth_headers):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    gpx = (
        b'<?xml version="1.0"?><gpx version="1.1" creator="Foretrex 401">'
        b'<trk><trkseg><trkpt lat="0" lon="0"><time>2026-01-01T00:00:00Z</time></trkpt>'
        b'<trkpt lat="0.001" lon="0"><time>2026-01-01T00:00:01Z</time></trkpt>'
        b"</trkseg></trk></gpx>"
    )
    response = app_client.post(
        "/upload", headers=HTMX_HEADERS, files={"gpx": ("activity.gpx", gpx, "application/gpx+xml")}
    )
    assert response.status_code == 200
    detail = app_client.get(response.headers["hx-redirect"])
    assert "Foretrex 401" in detail.text


def test_upload_rejects_invalid_activity_type(app_client, auth_headers, sample_gpx_bytes):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.post(
        "/upload",
        headers=HTMX_HEADERS,
        data={"activity_type": "swimming"},
        files={"gpx": ("activity.gpx", sample_gpx_bytes, "application/gpx+xml")},
    )
    assert response.status_code == 400
    assert "Invalid activity type" in response.text


def test_upload_rejects_junk_gpx(app_client, auth_headers):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.post(
        "/upload",
        headers=HTMX_HEADERS,
        files={"gpx": ("activity.gpx", b"not gpx", "application/gpx+xml")},
    )
    assert response.status_code == 400


def test_uploaded_activity_has_no_phone_stats(app_client, auth_headers, sample_gpx_bytes):
    _login_cookie_client(app_client, "admin@example.com", "admin-password-123")
    response = app_client.post(
        "/upload",
        headers=HTMX_HEADERS,
        files={"gpx": ("activity.gpx", sample_gpx_bytes, "application/gpx+xml")},
    )
    detail = app_client.get(response.headers["hx-redirect"])
    assert "Distance (phone)" not in detail.text
    assert "Distance (server)" in detail.text
