from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.sessions import read_session_cookie, session_cookie_name
from app.auth.web_sessions import resolve_web_session
from app.config import get_settings
from app.deps import db_session
from app.models.user import User
from app.repositories.users import SqlAlchemyUserRepository
from app.repositories.web_sessions import SqlAlchemyWebSessionRepository

HTMX_HEADER_NAME = "X-Requested-With"
HTMX_HEADER_VALUE = "htmx"

_REDIRECT_TO_LOGIN = HTTPException(
    status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"}
)


def get_web_user(
    request: Request,
    session: Annotated[Session, Depends(db_session)],
) -> User:
    """Resolves the signed-in user from the session cookie only (no bearer
    token — that's the phone's auth, not the browser's). Any failure redirects
    to /login rather than a bare 401, since a human is looking at this."""
    settings = get_settings()
    sr_session = request.cookies.get(session_cookie_name(secure_cookies=settings.secure_cookies))
    if sr_session is None:
        raise _REDIRECT_TO_LOGIN

    payload = read_session_cookie(settings.secret_key, sr_session)
    if payload is None:
        raise _REDIRECT_TO_LOGIN

    session_row = resolve_web_session(SqlAlchemyWebSessionRepository(session), payload.session_id)
    if session_row is None:
        raise _REDIRECT_TO_LOGIN

    users = SqlAlchemyUserRepository(session)
    user = users.get_by_id(session_row.user_id)
    if user is None or user.disabled_at is not None:
        raise _REDIRECT_TO_LOGIN
    if session_row.created_at < user.sessions_invalidated_at:
        raise _REDIRECT_TO_LOGIN
    return user


WebUser = Annotated[User, Depends(get_web_user)]


def get_web_admin(user: WebUser) -> User:
    """Admin pages 404 for non-admins, matching the API's admin routes —
    see docs/WEB-PLAN.md §5.2."""
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return user


WebAdmin = Annotated[User, Depends(get_web_admin)]


def get_current_web_session_id(
    _user: WebUser,
    request: Request,
) -> str | None:
    """The signed-in browser's own WebSession id, for routes that need to
    tell "this session" apart from the user's other active ones (the
    Sessions list on /settings). Depending on WebUser first guarantees the
    cookie has already been validated — this just re-reads its payload."""
    settings = get_settings()
    sr_session = request.cookies.get(session_cookie_name(secure_cookies=settings.secure_cookies))
    if sr_session is None:
        return None
    payload = read_session_cookie(settings.secret_key, sr_session)
    return payload.session_id if payload is not None else None


CurrentWebSessionId = Annotated[str | None, Depends(get_current_web_session_id)]


def require_htmx_header(request: Request) -> None:
    """CSRF guard for cookie-authenticated mutations (docs/WEB-PLAN.md §5.6):
    every state-changing web request must carry X-Requested-With: htmx, set
    globally via hx-headers on <body>. A cross-site form post can't add a
    custom header, so this is sufficient without a token. Bearer-token
    requests never hit these routes at all, so they're unaffected."""
    if request.headers.get(HTMX_HEADER_NAME) != HTMX_HEADER_VALUE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
