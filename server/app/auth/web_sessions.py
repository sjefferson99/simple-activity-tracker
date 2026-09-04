"""Session-row lifecycle shared by the API's cookie-auth path
(app/auth/current_user.py) and the web layer's (app/web/deps.py) — see
docs/SERVER-PRODUCTION-PLAN.md S4. A signed cookie alone (the pre-S4 design)
never actually expires server-side until its 30-day itsdangerous max_age
lapses, so a copied cookie survives logout. Backing it with a WebSession row
lets logout, an idle timeout, and a "sign out other browsers" action all
revoke it immediately.
"""

from datetime import UTC, datetime, timedelta

from app.models.web_session import WebSession
from app.repositories.web_sessions import WebSessionRepository

# Absolute lifetime matches the signed cookie's own max_age (sessions.py) —
# whichever check runs first rejects an old session, so keeping them equal
# just avoids a confusing gap where one still trusts a cookie the other doesn't.
ABSOLUTE_LIFETIME = timedelta(days=30)
IDLE_TIMEOUT = timedelta(days=14)
# last_seen_at is written on every authenticated request by default, which
# would make every request a write — only bump it if it's staler than this,
# same tradeoff device_tokens.last_used_at already makes (see R2 in the plan).
_LAST_SEEN_BUMP_INTERVAL = timedelta(hours=1)


def create_web_session(
    repo: WebSessionRepository, *, user_id: str, user_agent: str | None
) -> WebSession:
    now = datetime.now(UTC)
    session_row = WebSession(
        user_id=user_id,
        created_at=now,
        last_seen_at=now,
        user_agent=(user_agent or "")[:300] or None,
    )
    repo.add(session_row)
    return session_row


def resolve_web_session(repo: WebSessionRepository, session_id: str) -> WebSession | None:
    """Looks up an active session row, enforces its absolute lifetime and
    idle timeout, and bumps last_seen_at (at most once per
    _LAST_SEEN_BUMP_INTERVAL). Returns None for anything invalid/expired —
    callers don't need to distinguish "not found" from "expired"."""
    session_row = repo.get_by_id(session_id)
    if session_row is None or session_row.revoked_at is not None:
        return None

    now = datetime.now(UTC)
    if now - session_row.created_at > ABSOLUTE_LIFETIME:
        return None
    if now - session_row.last_seen_at > IDLE_TIMEOUT:
        return None

    if now - session_row.last_seen_at > _LAST_SEEN_BUMP_INTERVAL:
        session_row.last_seen_at = now

    return session_row
