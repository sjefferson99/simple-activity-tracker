import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.config import get_settings
from app.models.user import User
from app.repositories.users import SqlAlchemyUserRepository

_logger = logging.getLogger("app.bootstrap")


def bootstrap_admin_if_needed(session: Session) -> None:
    """If SR_ADMIN_EMAIL/SR_ADMIN_PASSWORD are set and no users exist yet,
    creates that first admin. Silent no-op otherwise — this runs on every
    startup, so it must never touch an already-populated users table.

    SR_ADMIN_PASSWORD only ever does anything on that first, empty-database
    run — see docs/SERVER-PRODUCTION-PLAN.md D3. Once at least one user
    exists, leaving it set in the deployment's env just means the plaintext
    password sits there indefinitely for no further effect, so we warn once
    per startup rather than silently ignoring it."""
    settings = get_settings()
    users = SqlAlchemyUserRepository(session)
    existing_users = users.list_all()

    if existing_users:
        if settings.admin_password:
            _logger.warning(
                "SR_ADMIN_PASSWORD is set but users already exist — it has no effect after "
                "the first startup and can be removed from this deployment's configuration."
            )
        return

    if not settings.admin_email or not settings.admin_password:
        return

    now = datetime.now(UTC)
    admin = User(
        email=settings.admin_email.lower(),
        password_hash=hash_password(settings.admin_password),
        display_name="Admin",
        is_admin=True,
        sessions_invalidated_at=now,
        created_at=now,
    )
    users.add(admin)
    session.commit()
