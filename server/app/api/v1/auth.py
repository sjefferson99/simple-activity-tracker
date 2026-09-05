from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.v1.errors import api_error
from app.api.v1.schemas import (
    ChangePasswordRequest,
    DeviceOut,
    LoginRequest,
    LoginResponse,
    UserOut,
)
from app.audit import log_audit_event
from app.auth.current_user import CurrentUser, bearer_token_from_header
from app.auth.device_tokens import generate_device_token, hash_device_token
from app.auth.passwords import hash_password, verify_or_burn, verify_password
from app.auth.rate_limit import account_action_rate_limiter, login_rate_limiter
from app.deps import db_session
from app.models.device_token import DeviceToken
from app.repositories.device_tokens import SqlAlchemyDeviceTokenRepository
from app.repositories.users import SqlAlchemyUserRepository
from app.repositories.web_sessions import SqlAlchemyWebSessionRepository

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_INVALID_CREDENTIALS = "Invalid email or password"


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    request: Request,
    session: Annotated[Session, Depends(db_session)],
) -> LoginResponse:
    client_ip = _client_ip(request)
    if not login_rate_limiter.allow(f"ip:{client_ip}") or not login_rate_limiter.allow(
        f"email:{body.email.lower()}"
    ):
        raise api_error(429, "rate_limited", "Too many login attempts. Try again shortly.")

    users = SqlAlchemyUserRepository(session)
    user = users.get_by_email(body.email)
    valid_user = user if user is not None and user.disabled_at is None else None
    password_ok = verify_or_burn(
        body.password, valid_user.password_hash if valid_user is not None else None
    )
    if valid_user is None or not password_ok:
        log_audit_event("login.failure", client_ip=client_ip, email=body.email.lower())
        raise api_error(401, "invalid_credentials", _INVALID_CREDENTIALS)
    user = valid_user

    log_audit_event("login.success", actor_id=user.id, client_ip=client_ip)
    secret = generate_device_token()
    now = datetime.now(UTC)
    token_row = DeviceToken(
        user_id=user.id,
        name=body.device_name,
        token_hash=hash_device_token(secret),
        created_at=now,
    )
    SqlAlchemyDeviceTokenRepository(session).add(token_row)
    session.flush()

    return LoginResponse(
        token=secret,
        device=DeviceOut(
            id=token_row.id,
            name=token_row.name,
            created_at=token_row.created_at,
            last_used_at=token_row.last_used_at,
        ),
        user=UserOut(
            id=user.id, email=user.email, display_name=user.display_name, is_admin=user.is_admin
        ),
    )


@router.post("/logout", status_code=204)
def logout(request: Request, session: Annotated[Session, Depends(db_session)]) -> None:
    bearer = bearer_token_from_header(request)
    if bearer is None:
        raise api_error(401, "unauthorized", "Not authenticated")
    tokens = SqlAlchemyDeviceTokenRepository(session)
    token_row = tokens.get_by_hash(hash_device_token(bearer))
    if token_row is not None and token_row.revoked_at is None:
        token_row.revoked_at = datetime.now(UTC)
        log_audit_event(
            "token.revoked",
            actor_id=token_row.user_id,
            target_id=token_row.id,
            client_ip=_client_ip(request),
        )


me_router = APIRouter(prefix="/api/v1/me", tags=["me"])


@me_router.get("", response_model=UserOut)
def get_me(user: CurrentUser) -> UserOut:
    return UserOut(
        id=user.id, email=user.email, display_name=user.display_name, is_admin=user.is_admin
    )


@me_router.get("/devices", response_model=list[DeviceOut])
def list_devices(
    user: CurrentUser, session: Annotated[Session, Depends(db_session)]
) -> list[DeviceOut]:
    tokens = SqlAlchemyDeviceTokenRepository(session)
    return [
        DeviceOut(id=t.id, name=t.name, created_at=t.created_at, last_used_at=t.last_used_at)
        for t in tokens.list_for_user(user.id)
    ]


@me_router.delete("/devices/{device_id}", status_code=204)
def revoke_device(
    device_id: str,
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
) -> None:
    tokens = SqlAlchemyDeviceTokenRepository(session)
    token_row = tokens.get_for_user(user.id, device_id)
    if token_row is None:
        raise api_error(404, "not_found", "Device not found")
    token_row.revoked_at = datetime.now(UTC)
    log_audit_event(
        "token.revoked", actor_id=user.id, target_id=token_row.id, client_ip=_client_ip(request)
    )


@me_router.put("/password", status_code=204)
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
) -> None:
    client_ip = _client_ip(request)
    if not account_action_rate_limiter.allow(f"ip:{client_ip}"):
        raise api_error(429, "rate_limited", "Too many attempts. Try again shortly.")

    if not verify_password(body.current_password, user.password_hash):
        raise api_error(401, "invalid_credentials", "Current password is incorrect")

    user.password_hash = hash_password(body.new_password)
    user.sessions_invalidated_at = datetime.now(UTC)

    presenting_token_id: str | None = None
    bearer = bearer_token_from_header(request)
    if bearer is not None:
        token_row = SqlAlchemyDeviceTokenRepository(session).get_by_hash(hash_device_token(bearer))
        if token_row is not None:
            presenting_token_id = token_row.id

    SqlAlchemyDeviceTokenRepository(session).revoke_all_for_user(
        user.id, except_id=presenting_token_id
    )
    # No "presenting web session" concept from a bearer-authenticated
    # request — a password change via the phone app signs every browser out.
    SqlAlchemyWebSessionRepository(session).revoke_all_for_user(user.id)
    log_audit_event(
        "user.password_reset", actor_id=user.id, target_id=user.id, client_ip=_client_ip(request)
    )
