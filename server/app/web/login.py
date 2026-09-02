from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response
from sqlalchemy.orm import Session

from app.auth.passwords import verify_password
from app.auth.rate_limit import login_rate_limiter
from app.auth.sessions import SESSION_COOKIE_NAME, create_session_cookie
from app.config import get_settings
from app.deps import db_session
from app.repositories.users import SqlAlchemyUserRepository
from app.web.deps import require_htmx_header
from app.web.templating import templates

router = APIRouter(tags=["web"], include_in_schema=False)

_INVALID_CREDENTIALS = "Invalid email or password"


def set_session_cookie(response: Response, user_id: str) -> None:
    settings = get_settings()
    cookie_value = create_session_cookie(settings.secret_key or "", user_id)
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

    if (
        rate_limited
        or user is None
        or user.disabled_at is not None
        or not verify_password(password, user.password_hash)
    ):
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

    response = Response(status_code=200, headers={"HX-Redirect": "/"})
    set_session_cookie(response, user.id)
    return response


@router.post("/logout", dependencies=[Depends(require_htmx_header)])
def logout() -> Response:
    out = Response(status_code=200, headers={"HX-Redirect": "/login"})
    out.delete_cookie(SESSION_COOKIE_NAME)
    return out
