from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.sessions import SESSION_COOKIE_NAME, read_session_cookie
from app.config import get_settings
from app.deps import db_session
from app.models.user import User
from app.repositories.users import SqlAlchemyUserRepository

HTMX_HEADER_NAME = "X-Requested-With"
HTMX_HEADER_VALUE = "htmx"

_REDIRECT_TO_LOGIN = HTTPException(
    status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"}
)


def get_web_user(
    session: Annotated[Session, Depends(db_session)],
    sr_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> User:
    """Resolves the signed-in user from the session cookie only (no bearer
    token — that's the phone's auth, not the browser's). Any failure redirects
    to /login rather than a bare 401, since a human is looking at this."""
    if sr_session is None:
        raise _REDIRECT_TO_LOGIN

    payload = read_session_cookie(get_settings().secret_key, sr_session)
    if payload is None:
        raise _REDIRECT_TO_LOGIN

    users = SqlAlchemyUserRepository(session)
    user = users.get_by_id(payload.user_id)
    if user is None or user.disabled_at is not None:
        raise _REDIRECT_TO_LOGIN
    if payload.issued_at < user.sessions_invalidated_at:
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


def require_htmx_header(request: Request) -> None:
    """CSRF guard for cookie-authenticated mutations (docs/WEB-PLAN.md §5.6):
    every state-changing web request must carry X-Requested-With: htmx, set
    globally via hx-headers on <body>. A cross-site form post can't add a
    custom header, so this is sufficient without a token. Bearer-token
    requests never hit these routes at all, so they're unaffected."""
    if request.headers.get(HTMX_HEADER_NAME) != HTMX_HEADER_VALUE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
