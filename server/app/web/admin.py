from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Header, Request, Response
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.config import get_settings
from app.deps import db_session
from app.models.user import User
from app.repositories.activities import SqlAlchemyActivityRepository
from app.repositories.activity_analyses import SqlAlchemyActivityAnalysisRepository
from app.repositories.device_tokens import SqlAlchemyDeviceTokenRepository
from app.repositories.users import SqlAlchemyUserRepository
from app.storage.blob_store import LocalFileBlobStore
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
    will_demote = want_admin is False and target.is_admin
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
    if will_demote or (will_disable and target.is_admin):
        if repo.count_admins_enabled() <= 1:
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

    session.flush()
    return templates.TemplateResponse(
        request, "partials/admin_user_list.html", _list_context(repo, admin)
    )


@router.post("/users/{user_id}/password", dependencies=[Depends(require_htmx_header)])
def admin_reset_password(
    user_id: str,
    request: Request,
    admin: WebAdmin,
    session: Annotated[Session, Depends(db_session)],
    hx_prompt: Annotated[str | None, Header()] = None,
) -> Response:
    repo = SqlAlchemyUserRepository(session)
    target = repo.get_by_id(user_id)
    if target is None:
        return Response(status_code=404)

    if not hx_prompt or len(hx_prompt) < 8:
        return templates.TemplateResponse(
            request,
            "partials/admin_user_list.html",
            _list_context(repo, admin, error="Password must be at least 8 characters"),
            status_code=400,
        )

    target.password_hash = hash_password(hx_prompt)
    _invalidate_sessions_and_tokens(session, target)
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

    cursor: str | None = None
    while True:
        page = activities_repo.list_for_user(target.id, limit=200, cursor=cursor)
        for activity in page.activities:
            analysis = analyses_repo.get_by_activity_id(activity.id)
            if analysis is not None:
                analyses_repo.delete(analysis)
                session.flush()
            blob_store.delete(activity.gpx_blob_key)
            activities_repo.delete(activity)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor

    SqlAlchemyDeviceTokenRepository(session).delete_all_for_user(target.id)
    session.flush()
    repo.delete(target)

    return templates.TemplateResponse(
        request, "partials/admin_user_list.html", _list_context(repo, admin)
    )
