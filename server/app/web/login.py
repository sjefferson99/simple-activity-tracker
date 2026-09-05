from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Form, Request, Response
from sqlalchemy.orm import Session

from app.audit import log_audit_event
from app.auth.passwords import verify_or_burn
from app.auth.rate_limit import login_rate_limiter
from app.auth.sessions import SESSION_COOKIE_NAME, create_session_cookie, read_session_cookie
from app.auth.web_sessions import create_web_session
from app.config import get_settings
from app.deps import db_session
from app.repositories.users import SqlAlchemyUserRepository
from app.repositories.web_sessions import SqlAlchemyWebSessionRepository
from app.web.deps import require_htmx_header
from app.web.templating import templates

router = APIRouter(tags=["web"], include_in_schema=False)

_INVALID_CREDENTIALS = "Invalid email or password"


def set_session_cookie(
    response: Response, session: Session, *, user_id: str, user_agent: str | None
) -> None:
    """Creates a new WebSession row for this sign-in and signs a cookie
    against its id — the row is what logout/idle-timeout/"sign out other
    browsers" actually act on; the cookie alone is just a bearer of the id."""
    settings = get_settings()
    session_row = create_web_session(
        SqlAlchemyWebSessionRepository(session), user_id=user_id, user_agent=user_agent
    )
    session.flush()
    cookie_value = create_session_cookie(settings.secret_key, session_row.id)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        cookie_value,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        max_age=30 * 24 * 60 * 60,
    )


@router.get("/login")
def login_page(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "login.html",
        {"user": None, "allow_registration": get_settings().allow_registration},
    )


@router.post("/login", dependencies=[Depends(require_htmx_header)])
def login_submit(
    request: Request,
    session: Annotated[Session, Depends(db_session)],
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> Response:
    client_ip = request.client.host if request.client else "unknown"
    rate_limited = not login_rate_limiter.allow(f"ip:{client_ip}") or not login_rate_limiter.allow(
        f"email:{email.lower()}"
    )

    users = SqlAlchemyUserRepository(session)
    user = None if rate_limited else users.get_by_email(email)
    valid_user = user if user is not None and user.disabled_at is None else None

    if rate_limited:
        password_ok = False
    else:
        # Always runs a real argon2 verify, even for an unknown/disabled
        # email, so the response time can't be used to enumerate accounts —
        # see docs/SERVER-PRODUCTION-PLAN.md S6.
        password_ok = verify_or_burn(
            password, valid_user.password_hash if valid_user is not None else None
        )

    if rate_limited or valid_user is None or not password_ok:
        if not rate_limited:
            log_audit_event("login.failure", client_ip=client_ip, email=email.lower())
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "user": None,
                "error": "Too many attempts, try again shortly"
                if rate_limited
                else _INVALID_CREDENTIALS,
                "email": email,
                "allow_registration": get_settings().allow_registration,
            },
            status_code=401,
        )

    log_audit_event("login.success", actor_id=valid_user.id, client_ip=client_ip)
    response = Response(status_code=200, headers={"HX-Redirect": "/"})
    set_session_cookie(
        response, session, user_id=valid_user.id, user_agent=request.headers.get("user-agent")
    )
    return response


@router.post("/logout", dependencies=[Depends(require_htmx_header)])
def logout(
    request: Request,
    session: Annotated[Session, Depends(db_session)],
    sr_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> Response:
    out = Response(status_code=200, headers={"HX-Redirect": "/login"})
    settings = get_settings()
    if sr_session is not None:
        payload = read_session_cookie(settings.secret_key, sr_session)
        if payload is not None:
            row = SqlAlchemyWebSessionRepository(session).get_by_id(payload.session_id)
            if row is not None and row.revoked_at is None:
                row.revoked_at = datetime.now(UTC)
                log_audit_event(
                    "session.revoked",
                    actor_id=row.user_id,
                    target_id=row.id,
                    client_ip=request.client.host if request.client else "unknown",
                )
    out.delete_cookie(
        SESSION_COOKIE_NAME,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
    )
    return out
