from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response
from sqlalchemy.orm import Session

from app.audit import log_audit_event
from app.auth.passwords import hash_password, verify_password
from app.auth.rate_limit import account_action_rate_limiter
from app.deps import db_session
from app.repositories.device_tokens import SqlAlchemyDeviceTokenRepository
from app.repositories.web_sessions import SqlAlchemyWebSessionRepository
from app.validation import ValidationFailedError, validate_password
from app.web.deps import CurrentWebSessionId, WebUser, require_htmx_header
from app.web.login import set_session_cookie
from app.web.templating import templates

router = APIRouter(tags=["web"], include_in_schema=False)


def _session_list_context(
    session: Session, user_id: str, current_session_id: str | None
) -> dict[str, object]:
    return {
        "sessions": SqlAlchemyWebSessionRepository(session).list_active_for_user(user_id),
        "current_session_id": current_session_id,
    }


@router.get("/settings")
def settings_page(
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    current_session_id: CurrentWebSessionId,
) -> Response:
    context = {"user": user, **_session_list_context(session, user.id, current_session_id)}
    return templates.TemplateResponse(request, "settings.html", context)


@router.delete("/settings/sessions/{session_id}", dependencies=[Depends(require_htmx_header)])
def revoke_session(
    session_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    current_session_id: CurrentWebSessionId,
) -> Response:
    if session_id == current_session_id:
        # Revoking your own live session here would immediately invalidate
        # the cookie this very request is authenticated with — send the user
        # through the real logout flow instead, which handles that cleanly.
        return Response(status_code=400)

    row = SqlAlchemyWebSessionRepository(session).get_active_for_user(user.id, session_id)
    if row is not None:
        SqlAlchemyWebSessionRepository(session).revoke(row)
        log_audit_event(
            "session.revoked",
            actor_id=user.id,
            target_id=row.id,
            client_ip=request.client.host if request.client else "unknown",
        )

    context = {"user": user, **_session_list_context(session, user.id, current_session_id)}
    return templates.TemplateResponse(request, "partials/session_list.html", context)


@router.put("/settings/password", dependencies=[Depends(require_htmx_header)])
def change_password(
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    current_password: Annotated[str, Form()],
    new_password: Annotated[str, Form()],
) -> Response:
    client_ip = request.client.host if request.client else "unknown"
    if not account_action_rate_limiter.allow(f"ip:{client_ip}"):
        return templates.TemplateResponse(
            request,
            "partials/change_password_form.html",
            {"user": user, "error": "Too many attempts, try again shortly"},
            status_code=429,
        )

    if not verify_password(current_password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "partials/change_password_form.html",
            {"user": user, "error": "Current password is incorrect"},
            status_code=401,
        )

    try:
        new_password = validate_password(new_password)
    except ValidationFailedError as exc:
        return templates.TemplateResponse(
            request,
            "partials/change_password_form.html",
            {"user": user, "error": str(exc)},
            status_code=400,
        )

    user.password_hash = hash_password(new_password)
    user.sessions_invalidated_at = datetime.now(UTC)
    SqlAlchemyDeviceTokenRepository(session).revoke_all_for_user(user.id)
    # Every WebSession row is revoked here, including this browser's current
    # one — set_session_cookie() below mints a brand new row (created_at >=
    # the sessions_invalidated_at bump above) rather than trying to spare the
    # old row, so there's never a stale row left active alongside the new one.
    SqlAlchemyWebSessionRepository(session).revoke_all_for_user(user.id)
    log_audit_event(
        "user.password_reset",
        actor_id=user.id,
        target_id=user.id,
        client_ip=request.client.host if request.client else "unknown",
    )

    response = templates.TemplateResponse(
        request, "partials/change_password_form.html", {"user": user, "success": True}
    )
    set_session_cookie(
        response, session, user_id=user.id, user_agent=request.headers.get("user-agent")
    )
    return response
