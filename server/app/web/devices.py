from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.audit import log_audit_event
from app.deps import db_session
from app.repositories.device_tokens import SqlAlchemyDeviceTokenRepository
from app.web.deps import WebUser, require_htmx_header
from app.web.templating import templates

router = APIRouter(tags=["web"], include_in_schema=False)


@router.get("/devices")
def devices_page(
    request: Request, user: WebUser, session: Annotated[Session, Depends(db_session)]
) -> Response:
    devices = SqlAlchemyDeviceTokenRepository(session).list_for_user(user.id)
    context = {"user": user, "devices": devices}
    if request.headers.get("hx-request") == "true":
        return templates.TemplateResponse(request, "partials/device_list.html", context)
    return templates.TemplateResponse(request, "devices.html", context)


@router.delete("/devices/{device_id}", dependencies=[Depends(require_htmx_header)])
def revoke_device(
    device_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    tokens = SqlAlchemyDeviceTokenRepository(session)
    token_row = tokens.get_for_user(user.id, device_id)
    if token_row is not None and token_row.revoked_at is None:
        token_row.revoked_at = datetime.now(UTC)
        log_audit_event(
            "token.revoked",
            actor_id=user.id,
            target_id=token_row.id,
            client_ip=request.client.host if request.client else "unknown",
        )
    devices = tokens.list_for_user(user.id)
    return templates.TemplateResponse(
        request, "partials/device_list.html", {"user": user, "devices": devices}
    )
