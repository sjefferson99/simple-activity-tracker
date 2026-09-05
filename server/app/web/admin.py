from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request, Response
from sqlalchemy.orm import Session

from app.audit import log_audit_event
from app.auth.passwords import hash_password
from app.config import get_settings
from app.deps import db_session
from app.models.user import User
from app.repositories.activities import SqlAlchemyActivityRepository
from app.repositories.activity_analyses import SqlAlchemyActivityAnalysisRepository
from app.repositories.device_tokens import SqlAlchemyDeviceTokenRepository
from app.repositories.users import SqlAlchemyUserRepository
from app.repositories.web_sessions import SqlAlchemyWebSessionRepository
from app.storage.blob_store import LocalFileBlobStore
from app.validation import ValidationFailedError, normalize_email, validate_name, validate_password
from app.web.deps import WebAdmin, require_htmx_header
from app.web.templating import templates

router = APIRouter(prefix="/admin", tags=["web"], include_in_schema=False)


def _user_row(repo: SqlAlchemyUserRepository, user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "is_admin": user.is_admin,
        "disabled": user.disabled_at is not None,
        "activity_count": repo.count_activities(user.id),
        "last_activity_at": repo.last_activity_at(user.id),
    }


def _list_context(repo: SqlAlchemyUserRepository, admin: User, **extra: Any) -> dict[str, Any]:
    return {
        "user": admin,
        "current_admin_id": admin.id,
        "users": [_user_row(repo, u) for u in repo.list_all()],
        **extra,
    }


def _invalidate_sessions_and_tokens(session: Session, target: User) -> None:
    target.sessions_invalidated_at = datetime.now(UTC)
    SqlAlchemyDeviceTokenRepository(session).revoke_all_for_user(target.id)
    SqlAlchemyWebSessionRepository(session).revoke_all_for_user(target.id)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/users")
def admin_users_page(
    request: Request, admin: WebAdmin, session: Annotated[Session, Depends(db_session)]
) -> Response:
    repo = SqlAlchemyUserRepository(session)
    return templates.TemplateResponse(request, "admin_users.html", _list_context(repo, admin))


@router.post("/users", dependencies=[Depends(require_htmx_header)])
def admin_create_user(
    request: Request,
    admin: WebAdmin,
    session: Annotated[Session, Depends(db_session)],
    display_name: Annotated[str, Form()],
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    is_admin: Annotated[str | None, Form()] = None,
) -> Response:
    repo = SqlAlchemyUserRepository(session)
    try:
        email = normalize_email(email)
        display_name = validate_name(display_name, field="Display name")
        password = validate_password(password)
    except ValidationFailedError as exc:
        return templates.TemplateResponse(
            request,
            "admin_users.html",
            _list_context(repo, admin, create_error=str(exc)),
            status_code=400,
        )

    if repo.get_by_email(email) is not None:
        return templates.TemplateResponse(
            request,
            "admin_users.html",
            _list_context(repo, admin, create_error="A user with this email already exists"),
            status_code=409,
        )

    now = datetime.now(UTC)
    user = User(
        email=email.lower(),
        password_hash=hash_password(password),
        display_name=display_name,
        is_admin=is_admin == "true",
        sessions_invalidated_at=now,
        created_at=now,
    )
    repo.add(user)
    session.flush()
    log_audit_event(
        "user.created", actor_id=admin.id, target_id=user.id, client_ip=_client_ip(request)
    )
    return templates.TemplateResponse(request, "admin_users.html", _list_context(repo, admin))


@router.patch("/users/{user_id}", dependencies=[Depends(require_htmx_header)])
def admin_patch_user(
    user_id: str,
    request: Request,
    admin: WebAdmin,
    session: Annotated[Session, Depends(db_session)],
    is_admin: Annotated[str | None, Form()] = None,
    disabled: Annotated[str | None, Form()] = None,
) -> Response:
    repo = SqlAlchemyUserRepository(session)
    target = repo.get_by_id(user_id)
    if target is None:
        return Response(status_code=404)

    want_admin = is_admin == "true" if is_admin is not None else None
    want_disabled = disabled == "true" if disabled is not None else None

    is_self = target.id == admin.id
    will_promote = want_admin is True and not target.is_admin
    will_demote = want_admin is False and target.is_admin
    will_enable = want_disabled is False and target.disabled_at is not None
    will_disable = want_disabled is True and target.disabled_at is None

    # Guards mirror app/api/v1/admin.py:patch_user — see that module's
    # comments for why the "last admin" branch can't currently be reached.
    if is_self and (will_demote or will_disable):
        return templates.TemplateResponse(
            request,
            "partials/admin_user_list.html",
            _list_context(repo, admin, error="You cannot demote or disable your own account"),
            status_code=400,
        )
    if (will_demote or (will_disable and target.is_admin)) and repo.count_admins_enabled() <= 1:
        return templates.TemplateResponse(
            request,
            "partials/admin_user_list.html",
            _list_context(repo, admin, error="Cannot remove the last enabled admin"),
            status_code=400,
        )

    if want_admin is not None:
        target.is_admin = want_admin
    if want_disabled is not None:
        target.disabled_at = datetime.now(UTC) if want_disabled else None

    if will_disable:
        _invalidate_sessions_and_tokens(session, target)

    client_ip = _client_ip(request)
    if will_promote:
        log_audit_event(
            "user.promoted", actor_id=admin.id, target_id=target.id, client_ip=client_ip
        )
    if will_demote:
        log_audit_event("user.demoted", actor_id=admin.id, target_id=target.id, client_ip=client_ip)
    if will_enable:
        log_audit_event("user.enabled", actor_id=admin.id, target_id=target.id, client_ip=client_ip)
    if will_disable:
        log_audit_event(
            "user.disabled", actor_id=admin.id, target_id=target.id, client_ip=client_ip
        )

    session.flush()
    return templates.TemplateResponse(
        request, "partials/admin_user_list.html", _list_context(repo, admin)
    )


@router.get("/users/{user_id}/password-form")
def admin_password_form(
    user_id: str,
    request: Request,
    admin: WebAdmin,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    repo = SqlAlchemyUserRepository(session)
    target = repo.get_by_id(user_id)
    if target is None:
        return Response(status_code=404)
    return templates.TemplateResponse(
        request, "partials/admin_user_password_form.html", {"u": _user_row(repo, target)}
    )


@router.get("/users/{user_id}/password-form/cancel")
def admin_password_form_cancel(
    user_id: str,
    request: Request,
    admin: WebAdmin,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    repo = SqlAlchemyUserRepository(session)
    target = repo.get_by_id(user_id)
    if target is None:
        return Response(status_code=404)
    return templates.TemplateResponse(
        request,
        "partials/admin_user_row.html",
        {"u": _user_row(repo, target), "current_admin_id": admin.id},
    )


@router.post("/users/{user_id}/password", dependencies=[Depends(require_htmx_header)])
def admin_reset_password(
    user_id: str,
    request: Request,
    admin: WebAdmin,
    session: Annotated[Session, Depends(db_session)],
    new_password: Annotated[str, Form()],
) -> Response:
    repo = SqlAlchemyUserRepository(session)
    target = repo.get_by_id(user_id)
    if target is None:
        return Response(status_code=404)

    try:
        new_password = validate_password(new_password)
    except ValidationFailedError as exc:
        return templates.TemplateResponse(
            request,
            "partials/admin_user_password_form.html",
            {"u": _user_row(repo, target), "error": str(exc)},
            status_code=400,
        )

    target.password_hash = hash_password(new_password)
    _invalidate_sessions_and_tokens(session, target)
    log_audit_event(
        "user.password_reset", actor_id=admin.id, target_id=target.id, client_ip=_client_ip(request)
    )
    return templates.TemplateResponse(
        request, "partials/admin_user_list.html", _list_context(repo, admin)
    )


@router.delete("/users/{user_id}", dependencies=[Depends(require_htmx_header)])
def admin_delete_user(
    user_id: str,
    request: Request,
    admin: WebAdmin,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    repo = SqlAlchemyUserRepository(session)
    target = repo.get_by_id(user_id)
    if target is None:
        return Response(status_code=404)
    target_id = target.id

    if target.id == admin.id:
        return templates.TemplateResponse(
            request,
            "partials/admin_user_list.html",
            _list_context(repo, admin, error="You cannot delete your own account"),
            status_code=400,
        )
    if target.is_admin and repo.count_admins_enabled() <= 1 and target.disabled_at is None:
        return templates.TemplateResponse(
            request,
            "partials/admin_user_list.html",
            _list_context(repo, admin, error="Cannot remove the last enabled admin"),
            status_code=400,
        )

    activities_repo = SqlAlchemyActivityRepository(session)
    analyses_repo = SqlAlchemyActivityAnalysisRepository(session)
    blob_store = LocalFileBlobStore(Path(get_settings().data_dir))

    blob_keys: list[str] = []
    cursor: str | None = None
    while True:
        page = activities_repo.list_for_user(target.id, limit=200, cursor=cursor)
        for activity in page.activities:
            analysis = analyses_repo.get_by_activity_id(activity.id)
            if analysis is not None:
                analyses_repo.delete(analysis)
                session.flush()
            blob_keys.append(activity.gpx_blob_key)
            activities_repo.delete(activity)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor

    SqlAlchemyDeviceTokenRepository(session).delete_all_for_user(target.id)
    SqlAlchemyWebSessionRepository(session).delete_all_for_user(target.id)
    session.flush()
    repo.delete(target)

    # Committed explicitly (see app/api/v1/activities.py:delete_activity for
    # why a BackgroundTask can't be used for this ordering) — build the
    # response context first, since it re-queries the user list and must
    # see the deletion, then delete the now-safely-orphaned blobs.
    session.commit()
    log_audit_event(
        "user.deleted", actor_id=admin.id, target_id=target_id, client_ip=_client_ip(request)
    )
    response = templates.TemplateResponse(
        request, "partials/admin_user_list.html", _list_context(repo, admin)
    )
    for blob_key in blob_keys:
        blob_store.delete(blob_key)
    return response
