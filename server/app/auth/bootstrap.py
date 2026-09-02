from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.config import get_settings
from app.models.user import User
from app.repositories.users import SqlAlchemyUserRepository


def bootstrap_admin_if_needed(session: Session) -> None:
    """If SR_ADMIN_EMAIL/SR_ADMIN_PASSWORD are set and no users exist yet,
    creates that first admin. Silent no-op otherwise — this runs on every
    startup, so it must never touch an already-populated users table."""
    settings = get_settings()
    if not settings.admin_email or not settings.admin_password:
        return

    users = SqlAlchemyUserRepository(session)
    if users.list_all():
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
