"""R2 (docs/SERVER-PRODUCTION-PLAN.md): device_tokens.last_used_at should
only be bumped when it's null or stale, not on every authenticated bearer
request — otherwise every read becomes a write transaction."""

from datetime import UTC, datetime, timedelta

from app.auth.current_user import _LAST_USED_BUMP_INTERVAL
from app.db import get_session_factory
from app.models.device_token import DeviceToken


def _get_token_row(admin_token: str) -> DeviceToken:
    from app.auth.device_tokens import hash_device_token

    with get_session_factory()() as session:
        row = session.query(DeviceToken).filter_by(token_hash=hash_device_token(admin_token)).one()
        session.expunge(row)
        return row


def test_last_used_at_is_set_on_first_use(app_client, admin_token, auth_headers) -> None:
    row_before = _get_token_row(admin_token)
    assert row_before.last_used_at is None

    response = app_client.get("/api/v1/me", headers=auth_headers)
    assert response.status_code == 200

    row_after = _get_token_row(admin_token)
    assert row_after.last_used_at is not None


def test_last_used_at_is_not_bumped_again_within_the_interval(
    app_client, admin_token, auth_headers
) -> None:
    app_client.get("/api/v1/me", headers=auth_headers)
    row_after_first = _get_token_row(admin_token)

    response = app_client.get("/api/v1/me", headers=auth_headers)
    assert response.status_code == 200

    row_after_second = _get_token_row(admin_token)
    assert row_after_second.last_used_at == row_after_first.last_used_at


def test_last_used_at_is_bumped_again_once_stale(app_client, admin_token, auth_headers) -> None:
    from app.auth.device_tokens import hash_device_token

    stale = datetime.now(UTC) - _LAST_USED_BUMP_INTERVAL - timedelta(seconds=1)
    with get_session_factory()() as session:
        row = session.query(DeviceToken).filter_by(token_hash=hash_device_token(admin_token)).one()
        row.last_used_at = stale
        session.commit()

    response = app_client.get("/api/v1/me", headers=auth_headers)
    assert response.status_code == 200

    row_after = _get_token_row(admin_token)
    assert row_after.last_used_at is not None
    assert row_after.last_used_at > stale
