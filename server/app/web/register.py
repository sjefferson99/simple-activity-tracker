from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.config import get_settings
from app.deps import db_session
from app.models.user import User
from app.repositories.users import SqlAlchemyUserRepository
from app.web.deps import require_htmx_header
from app.web.login import set_session_cookie
from app.web.templating import templates

router = APIRouter(tags=["web"], include_in_schema=False)


def _require_registration_open() -> None:
    if not get_settings().allow_registration:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.get("/register", dependencies=[Depends(_require_registration_open)])
def register_page(request: Request) -> Response:
    return templates.TemplateResponse(request, "register.html", {"user": None})


@router.post(
    "/register",
    dependencies=[Depends(_require_registration_open), Depends(require_htmx_header)],
)
def register_submit(
    request: Request,
    session: Annotated[Session, Depends(db_session)],
    display_name: Annotated[str, Form()],
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> Response:
    repo = SqlAlchemyUserRepository(session)
    if repo.get_by_email(email) is not None:
        # No user enumeration on login, but registration must tell the user
        # their email is taken or they can never recover — see
        # docs/WEB-PLAN.md §5.6 (that rule targets the login form).
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "user": None,
                "error": "An account with this email already exists",
                "display_name": display_name,
                "email": email,
            },
            status_code=409,
        )

    now = datetime.now(UTC)
    user = User(
        email=email.lower(),
        password_hash=hash_password(password),
        display_name=display_name,
        is_admin=False,
        sessions_invalidated_at=now,
        created_at=now,
    )
    repo.add(user)
    session.flush()

    response = Response(status_code=200, headers={"HX-Redirect": "/"})
    set_session_cookie(response, user.id)
    return response
