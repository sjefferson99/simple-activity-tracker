"""Saved split configs (issue #126): named, reusable split plans a user can
build on the web editor or on the phone, list/select on the phone, and edit
from either side. See docs/SPLIT-CONFIGS-PLAN.md §3.

Unlike Activity.split_plan (a per-activity snapshot taken at upload time,
never referencing a SplitConfig row — see app/models/activity.py), rows here
are the user's own curated, editable library. No pagination (§1 of the plan
doc — a small, manually curated list, same reasoning as /api/v1/me/devices).
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.errors import api_error
from app.api.v1.schemas import (
    SplitConfigCreateRequest,
    SplitConfigListResponse,
    SplitConfigOut,
    SplitConfigPatchRequest,
    SplitPlanIn,
)
from app.auth.current_user import CurrentUser
from app.auth.rate_limit import account_action_rate_limiter
from app.deps import db_session
from app.models.split_config import SplitConfig
from app.repositories.split_configs import SqlAlchemySplitConfigRepository

router = APIRouter(prefix="/api/v1/split-configs", tags=["split-configs"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _plan_to_json(plan: SplitPlanIn) -> dict[str, object]:
    return {
        "split_type": plan.split_type,
        "split_value": plan.split_value,
        "rolling_target_mps": plan.rolling_target_mps,
        "custom_splits": [[size, target] for size, target in plan.custom_splits],
        "targets_as": plan.targets_as,
    }


def _config_out(config: SplitConfig) -> SplitConfigOut:
    return SplitConfigOut(
        id=config.id,
        name=config.name,
        plan=SplitPlanIn.model_validate(config.plan),
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


def _require_rate_limit(request: Request) -> None:
    if not account_action_rate_limiter.allow(f"ip:{_client_ip(request)}"):
        raise api_error(429, "rate_limited", "Too many attempts. Try again shortly.")


@router.get("", response_model=SplitConfigListResponse)
def list_split_configs(
    user: CurrentUser, session: Annotated[Session, Depends(db_session)]
) -> SplitConfigListResponse:
    configs = SqlAlchemySplitConfigRepository(session).list_for_user(user.id)
    return SplitConfigListResponse(configs=[_config_out(c) for c in configs])


@router.get("/{config_id}", response_model=SplitConfigOut)
def get_split_config(
    config_id: str, user: CurrentUser, session: Annotated[Session, Depends(db_session)]
) -> SplitConfigOut:
    config = SqlAlchemySplitConfigRepository(session).get_for_user(user.id, config_id)
    if config is None:
        raise api_error(404, "not_found", "Split config not found")
    return _config_out(config)


@router.post("", response_model=SplitConfigOut)
def create_split_config(
    body: SplitConfigCreateRequest,
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
) -> SplitConfigOut:
    """Creates a new config, or — with overwrite=true — replaces an existing
    same-named one in place (same id, bumped updated_at). Without
    overwrite=true, a name collision is a 409 so the caller can ask the user
    to confirm and retry (see docs/SPLIT-CONFIGS-PLAN.md §3/§5.4)."""
    _require_rate_limit(request)
    repo = SqlAlchemySplitConfigRepository(session)

    if body.overwrite:
        existing = repo.get_by_name_for_user(user.id, body.name)
        if existing is not None:
            existing.plan = _plan_to_json(body.plan)
            existing.updated_at = datetime.now(UTC)
            session.flush()
            return _config_out(existing)

    now = datetime.now(UTC)
    config = SplitConfig(
        user_id=user.id,
        name=body.name,
        plan=_plan_to_json(body.plan),
        created_at=now,
        updated_at=now,
    )
    repo.add(config)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        # Same begin_nested()/IntegrityError dance as the activity upload
        # race in app/api/v1/activities.py — the Session is left in a
        # "rollback required" state after a caught IntegrityError until this
        # runs, or the very next statement raises PendingRollbackError
        # instead of the error we actually want to report.
        session.rollback()
        raise api_error(
            409,
            "name_conflict",
            f"A split config named '{body.name}' already exists. Retry with overwrite=true "
            "to replace it.",
        ) from exc
    return _config_out(config)


@router.patch("/{config_id}", response_model=SplitConfigOut)
def patch_split_config(
    config_id: str,
    body: SplitConfigPatchRequest,
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
) -> SplitConfigOut:
    _require_rate_limit(request)
    repo = SqlAlchemySplitConfigRepository(session)
    config = repo.get_for_user(user.id, config_id)
    if config is None:
        raise api_error(404, "not_found", "Split config not found")

    if body.name is not None and body.name != config.name:
        collision = repo.get_by_name_for_user(user.id, body.name)
        if collision is not None and collision.id != config.id:
            raise api_error(
                409, "name_conflict", f"A split config named '{body.name}' already exists."
            )
        config.name = body.name
    if body.plan is not None:
        config.plan = _plan_to_json(body.plan)
    config.updated_at = datetime.now(UTC)
    session.flush()
    return _config_out(config)


@router.delete("/{config_id}", status_code=204)
def delete_split_config(
    config_id: str,
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
) -> None:
    _require_rate_limit(request)
    repo = SqlAlchemySplitConfigRepository(session)
    config = repo.get_for_user(user.id, config_id)
    if config is None:
        raise api_error(404, "not_found", "Split config not found")
    repo.delete(config)
