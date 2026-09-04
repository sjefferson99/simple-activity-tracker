from datetime import UTC, datetime
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.device_tokens import hash_device_token
from app.auth.sessions import SESSION_COOKIE_NAME, read_session_cookie
from app.auth.web_sessions import resolve_web_session
from app.config import get_settings
from app.deps import db_session
from app.models.user import User
from app.repositories.device_tokens import SqlAlchemyDeviceTokenRepository
from app.repositories.users import SqlAlchemyUserRepository
from app.repositories.web_sessions import SqlAlchemyWebSessionRepository

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail={"error": {"code": "unauthorized", "message": "Not authenticated"}},
)


def _user_is_usable(user: User) -> bool:
    return user.disabled_at is None


def bearer_token_from_header(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header is None or not header.lower().startswith("bearer "):
        return None
    return header[len("bearer ") :].strip()


def get_current_user(
    request: Request,
    session: Annotated[Session, Depends(db_session)],
    sr_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> User:
    """Resolves the current user from a bearer token or the session cookie.
    Disabled users, revoked device tokens, and sessions issued before the
    user's sessions_invalidated_at are all rejected here — this is the one
    place "disable user" / "reset password" actually take effect."""
    bearer = bearer_token_from_header(request)
    users = SqlAlchemyUserRepository(session)

    if bearer is not None:
        tokens = SqlAlchemyDeviceTokenRepository(session)
        token_row = tokens.get_by_hash(hash_device_token(bearer))
        if token_row is None or token_row.revoked_at is not None:
            raise _UNAUTHORIZED
        user = users.get_by_id(token_row.user_id)
        if user is None or not _user_is_usable(user):
            raise _UNAUTHORIZED
        token_row.last_used_at = datetime.now(UTC)
        return user

    if sr_session is not None:
        payload = read_session_cookie(get_settings().secret_key, sr_session)
        if payload is None:
            raise _UNAUTHORIZED
        session_row = resolve_web_session(
            SqlAlchemyWebSessionRepository(session), payload.session_id
        )
        if session_row is None:
            raise _UNAUTHORIZED
        user = users.get_by_id(session_row.user_id)
        if user is None or not _user_is_usable(user):
            raise _UNAUTHORIZED
        if session_row.created_at < user.sessions_invalidated_at:
            raise _UNAUTHORIZED
        return user

    raise _UNAUTHORIZED


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_admin(user: CurrentUser) -> User:
    """Admin routes 404 rather than 403 for non-admins, so their existence
    isn't revealed to a user probing the API — see docs/WEB-PLAN.md §5.2."""
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return user


CurrentAdmin = Annotated[User, Depends(get_current_admin)]
