"""D3 (docs/SERVER-PRODUCTION-PLAN.md): SR_ADMIN_PASSWORD only ever creates
the first admin — leaving it set afterwards has no effect and should warn,
since a plaintext password sitting in a deployment's env for no reason is
worth flagging."""

import logging

from app.auth.bootstrap import bootstrap_admin_if_needed
from app.db import get_session_factory
from app.repositories.users import SqlAlchemyUserRepository


def test_bootstrap_creates_the_first_admin(app_client, monkeypatch) -> None:
    monkeypatch.setenv("SR_ADMIN_EMAIL", "first-admin@example.com")
    monkeypatch.setenv("SR_ADMIN_PASSWORD", "first-admin-password-123")
    from app.config import get_settings

    get_settings.cache_clear()

    with get_session_factory()() as session:
        bootstrap_admin_if_needed(session)
        users = SqlAlchemyUserRepository(session).list_all()

    assert len(users) == 1
    assert users[0].email == "first-admin@example.com"
    assert users[0].is_admin is True
    get_settings.cache_clear()


def test_warns_when_admin_password_still_set_after_users_exist(
    app_client, admin_token, monkeypatch, caplog
) -> None:
    monkeypatch.setenv("SR_ADMIN_PASSWORD", "leftover-password-still-in-env")
    from app.config import get_settings

    get_settings.cache_clear()

    with (
        get_session_factory()() as session,
        caplog.at_level(logging.WARNING, logger="app.bootstrap"),
    ):
        bootstrap_admin_if_needed(session)

    messages = [r.message for r in caplog.records if r.name == "app.bootstrap"]
    assert any("SR_ADMIN_PASSWORD" in m for m in messages)
    assert not any("leftover-password-still-in-env" in m for m in messages)
    get_settings.cache_clear()


def test_no_warning_when_admin_password_unset_after_users_exist(
    app_client, admin_token, monkeypatch, caplog
) -> None:
    monkeypatch.delenv("SR_ADMIN_PASSWORD", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()

    with (
        get_session_factory()() as session,
        caplog.at_level(logging.WARNING, logger="app.bootstrap"),
    ):
        bootstrap_admin_if_needed(session)

    messages = [r.message for r in caplog.records if r.name == "app.bootstrap"]
    assert not any("SR_ADMIN_PASSWORD" in m for m in messages)
    get_settings.cache_clear()
