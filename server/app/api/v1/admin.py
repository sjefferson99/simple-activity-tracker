from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.errors import api_error
from app.api.v1.schemas import (
    AdminCreateUserRequest,
    AdminPatchUserRequest,
    AdminSetPasswordRequest,
    AdminUserOut,
)
from app.auth.current_user import CurrentAdmin
from app.auth.passwords import hash_password
from app.config import get_settings
from app.deps import db_session
from app.models.user import User
from app.repositories.device_tokens import SqlAlchemyDeviceTokenRepository
from app.repositories.run_analyses import SqlAlchemyRunAnalysisRepository
from app.repositories.runs import SqlAlchemyRunRepository
from app.repositories.users import SqlAlchemyUserRepository
from app.storage.blob_store import LocalFileBlobStore

router = APIRouter(prefix="/api/v1/admin/users", tags=["admin"])


def _user_out(repo: SqlAlchemyUserRepository, user: User) -> AdminUserOut:
    return AdminUserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_admin=user.is_admin,
        disabled=user.disabled_at is not None,
        run_count=repo.count_runs(user.id),
        last_run_at=repo.last_run_at(user.id),
        created_at=user.created_at,
    )


def _invalidate_sessions_and_tokens(session: Session, user: User) -> None:
    user.sessions_invalidated_at = datetime.now(UTC)
    SqlAlchemyDeviceTokenRepository(session).revoke_all_for_user(user.id)


@router.get("", response_model=list[AdminUserOut])
def list_users(
    admin: CurrentAdmin, session: Annotated[Session, Depends(db_session)]
) -> list[AdminUserOut]:
    repo = SqlAlchemyUserRepository(session)
    return [_user_out(repo, u) for u in repo.list_all()]


@router.post("", response_model=AdminUserOut, status_code=201)
def create_user(
    body: AdminCreateUserRequest,
    admin: CurrentAdmin,
    session: Annotated[Session, Depends(db_session)],
) -> AdminUserOut:
    repo = SqlAlchemyUserRepository(session)
    if repo.get_by_email(body.email) is not None:
        raise api_error(409, "email_taken", "A user with this email already exists")

    now = datetime.now(UTC)
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        is_admin=body.is_admin,
        sessions_invalidated_at=now,
        created_at=now,
    )
    repo.add(user)
    session.flush()
    return _user_out(repo, user)


@router.patch("/{user_id}", response_model=AdminUserOut)
def patch_user(
    user_id: str,
    body: AdminPatchUserRequest,
    admin: CurrentAdmin,
    session: Annotated[Session, Depends(db_session)],
) -> AdminUserOut:
    repo = SqlAlchemyUserRepository(session)
    target = repo.get_by_id(user_id)
    if target is None:
        raise api_error(404, "not_found", "User not found")

    is_self = target.id == admin.id
    will_demote = body.is_admin is False and target.is_admin
    will_disable = body.disabled is True and target.disabled_at is None

    if is_self and (will_demote or will_disable):
        raise api_error(400, "cannot_modify_self", "You cannot demote or disable your own account")
    # Defense-in-depth: with the routes as they stand, cannot_modify_self
    # above always fires first (the only admin who could ever demote/disable
    # "the last enabled admin" is that admin itself), so this can't
    # currently be reached — kept in case a future route lets one admin
    # target another while only one admin remains (e.g. a superadmin role).
    if will_demote or (will_disable and target.is_admin):
        if repo.count_admins_enabled() <= 1:
            raise api_error(400, "last_admin", "Cannot remove the last enabled admin")

    if body.display_name is not None:
        target.display_name = body.display_name
    if body.is_admin is not None:
        target.is_admin = body.is_admin
    if body.disabled is not None:
        target.disabled_at = datetime.now(UTC) if body.disabled else None

    if will_disable:
        _invalidate_sessions_and_tokens(session, target)

    session.flush()
    return _user_out(repo, target)


@router.post("/{user_id}/password", status_code=204)
def reset_password(
    user_id: str,
    body: AdminSetPasswordRequest,
    admin: CurrentAdmin,
    session: Annotated[Session, Depends(db_session)],
) -> None:
    repo = SqlAlchemyUserRepository(session)
    target = repo.get_by_id(user_id)
    if target is None:
        raise api_error(404, "not_found", "User not found")

    target.password_hash = hash_password(body.new_password)
    _invalidate_sessions_and_tokens(session, target)


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: str,
    admin: CurrentAdmin,
    session: Annotated[Session, Depends(db_session)],
) -> None:
    repo = SqlAlchemyUserRepository(session)
    target = repo.get_by_id(user_id)
    if target is None:
        raise api_error(404, "not_found", "User not found")

    if target.id == admin.id:
        raise api_error(400, "cannot_modify_self", "You cannot delete your own account")
    # Same defense-in-depth note as patch_user: unreachable today, since the
    # only admin who could ever be "the last one" targeting themself is
    # already blocked by cannot_modify_self above.
    if target.is_admin and repo.count_admins_enabled() <= 1 and target.disabled_at is None:
        raise api_error(400, "last_admin", "Cannot remove the last enabled admin")

    runs_repo = SqlAlchemyRunRepository(session)
    analyses_repo = SqlAlchemyRunAnalysisRepository(session)
    blob_store = LocalFileBlobStore(Path(get_settings().data_dir))

    cursor: str | None = None
    while True:
        page = runs_repo.list_for_user(target.id, limit=200, cursor=cursor)
        for run in page.runs:
            analysis = analyses_repo.get_by_run_id(run.id)
            if analysis is not None:
                analyses_repo.delete(analysis)
                # See the matching comment in app/api/v1/runs.py:delete_run —
                # no relationship() means the analysis delete must be
                # flushed before the run delete, or the FK constraint fails.
                session.flush()
            blob_store.delete(run.gpx_blob_key)
            runs_repo.delete(run)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor

    SqlAlchemyDeviceTokenRepository(session).delete_all_for_user(target.id)
    session.flush()

    repo.delete(target)
