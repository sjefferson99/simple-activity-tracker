from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password, verify_password
from app.deps import db_session
from app.repositories.device_tokens import SqlAlchemyDeviceTokenRepository
from app.validation import ValidationFailed, validate_password
from app.web.deps import WebUser, require_htmx_header
from app.web.login import set_session_cookie
from app.web.templating import templates

router = APIRouter(tags=["web"], include_in_schema=False)


@router.get("/settings")
def settings_page(request: Request, user: WebUser) -> Response:
    return templates.TemplateResponse(request, "settings.html", {"user": user})


@router.put("/settings/password", dependencies=[Depends(require_htmx_header)])
def change_password(
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
) -> Response:
    if not verify_password(current_password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "partials/change_password_form.html",
            {"user": user, "error": "Current password is incorrect"},
            status_code=401,
        )

    try:
        new_password = validate_password(new_password)
    except ValidationFailed as exc:
        return templates.TemplateResponse(
            request,
            "partials/change_password_form.html",
            {"user": user, "error": str(exc)},
            status_code=400,
        )

    user.password_hash = hash_password(new_password)
    user.sessions_invalidated_at = datetime.now(UTC)
    SqlAlchemyDeviceTokenRepository(session).revoke_all_for_user(user.id)

    response = templates.TemplateResponse(
        request, "partials/change_password_form.html", {"user": user, "success": True}
    )
    # sessions_invalidated_at just moved to "now", which would also log this
    # browser out on its next request — re-mint the cookie so only *other*
    # sessions and every device token are invalidated, not this one.
    set_session_cookie(response, user.id)
    return response
