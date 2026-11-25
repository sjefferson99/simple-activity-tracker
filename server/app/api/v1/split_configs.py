"""Saved split configs (issue #126): named, reusable split plans a user can
build on the web editor or on the phone, list/select on the phone, and edit
from either side. See docs/SPLIT-CONFIGS-PLAN.md §3.

Issue #143 (docs/SPLIT-LIBRARY-PLAN.md, API level 4) adds folders, read-only
templates synced from split repos (listed alongside own configs, refused by
PATCH/DELETE), and import/export.

Unlike Activity.split_plan (a per-activity snapshot taken at upload time,
never referencing a SplitConfig row — see app/models/activity.py), rows here
are the user's own curated, editable library. No pagination (§1 of the plan
doc — a small, manually curated list, same reasoning as /api/v1/me/devices).
"""

import json
import re
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Query, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.errors import api_error
from app.api.v1.schemas import (
    SplitConfigCreateRequest,
    SplitConfigImportResponse,
    SplitConfigListResponse,
    SplitConfigOut,
    SplitConfigPatchRequest,
    SplitConfigSourceRef,
    SplitPlanIn,
    split_plan_in_to_json,
)
from app.auth.current_user import CurrentUser
from app.auth.rate_limit import account_action_rate_limiter
from app.deps import db_session
from app.models.split_config import SplitConfig
from app.repositories.split_configs import SqlAlchemySplitConfigRepository
from app.split_library import files, library

router = APIRouter(prefix="/api/v1/split-configs", tags=["split-configs"])

# Plenty for 500 configs; keeps a single request from being a memory hog.
MAX_IMPORT_BYTES = 2 * 1024 * 1024


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _plan_to_json(plan: SplitPlanIn) -> dict[str, object]:
    return split_plan_in_to_json(plan)


def config_out(visible: library.VisibleConfig) -> SplitConfigOut:
    config = visible.config
    return SplitConfigOut(
        id=config.id,
        name=config.name,
        plan=SplitPlanIn.model_validate(config.plan),
        created_at=config.created_at,
        updated_at=config.updated_at,
        uid=config.uid,
        folder=config.folder,
        folder_name=visible.folder_name,
        read_only=config.read_only,
        source=(
            SplitConfigSourceRef(id=visible.source.id, name=visible.source.name)
            if visible.source is not None
            else None
        ),
    )


def _own_out(config: SplitConfig) -> SplitConfigOut:
    return config_out(library.VisibleConfig(config=config, folder_name=config.folder, source=None))


def _require_rate_limit(request: Request) -> None:
    if not account_action_rate_limiter.allow(f"ip:{_client_ip(request)}"):
        raise api_error(429, "rate_limited", "Too many attempts. Try again shortly.")


def _read_only_error() -> Exception:
    return api_error(
        403,
        "read_only",
        "This is a template from a split repo and can't be changed. Copy it to make your own.",
    )


def schedule_due_syncs(session: Session, user_id: str, background_tasks: BackgroundTasks) -> None:
    """Subscribes the user to the default repo on first use, and re-syncs any
    stale source after the response. Commits first: a BackgroundTask runs
    before the db_session dependency's own commit (CLAUDE.md gotcha)."""
    library.ensure_default_source(session, user_id)
    due = library.due_source_ids(session, user_id)
    session.commit()
    if due:
        background_tasks.add_task(library.sync_in_background, due)


@router.get("", response_model=SplitConfigListResponse)
def list_split_configs(
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
    background_tasks: BackgroundTasks,
) -> SplitConfigListResponse:
    """Own configs plus templates from enabled folders of enabled sources,
    sorted by name. Older apps see templates as ordinary configs they can
    load, which is what hiding a folder controls (docs/SPLIT-LIBRARY-PLAN.md L7)."""
    schedule_due_syncs(session, user.id, background_tasks)
    return SplitConfigListResponse(
        configs=[config_out(v) for v in library.list_visible(session, user.id)]
    )


_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def export_filename(stem: str) -> str:
    cleaned = _SAFE_FILENAME_RE.sub("-", stem).strip("-.")[:80]
    return f"{cleaned or 'split-configs'}.json"


def build_export(
    session: Session, user_id: str, *, folder: str | None, ids: list[str]
) -> tuple[dict[str, object], str] | None:
    """(document, filename) for an export, or None if an id isn't found.
    One id → a single-config file (the format a template repo uses).
    Otherwise a bundle of the named configs, or of every own config (in
    `folder` when given)."""
    if ids:
        chosen = []
        for config_id in ids:
            visible = library.visible_config(session, user_id, config_id)
            if visible is None:
                return None
            chosen.append(visible)
        if len(chosen) == 1:
            return files.one_document(chosen[0].config), export_filename(chosen[0].config.name)
        return (
            files.bundle_document([(v.config, v.folder_name) for v in chosen]),
            export_filename("split-configs"),
        )
    own = SqlAlchemySplitConfigRepository(session).list_for_user(user_id)
    if folder is not None:
        own = [c for c in own if (c.folder or "") == folder]
    stem = f"split-configs-{folder}" if folder else "split-configs"
    return files.bundle_document([(c, c.folder) for c in own]), export_filename(stem)


def export_response(document: dict[str, object], filename: str) -> Response:
    return Response(
        content=json.dumps(document, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/export",
    responses={200: {"content": {"application/json": {}}, "description": "Split config file"}},
)
def export_split_configs(
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
    folder: Annotated[str | None, Query(max_length=200)] = None,
    config_id: Annotated[list[str] | None, Query(alias="id", max_length=500)] = None,
) -> Response:
    """Issue #143: a file to back up, move to another server or share. With
    one `id`, a single-config file (templates included); with several, a
    bundle of those; otherwise every own config, or those in `folder`."""
    built = build_export(session, user.id, folder=folder, ids=config_id or [])
    if built is None:
        raise api_error(404, "not_found", "Split config not found")
    return export_response(*built)


def run_import(session: Session, user_id: str, raw: bytes | object) -> SplitConfigImportResponse:
    try:
        parsed, errors = files.parse_document(raw)
    except files.DocumentError as exc:
        raise api_error(422, "invalid_file", f"Couldn't import: {exc}") from exc
    result = library.import_configs(session, user_id, parsed)
    return SplitConfigImportResponse(
        created=result.created,
        updated=result.updated,
        renamed=result.renamed,
        errors=errors,
    )


@router.post("/import", response_model=SplitConfigImportResponse)
def import_split_configs(
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
    document: Annotated[dict[str, Any], Body()],
) -> SplitConfigImportResponse:
    """Issue #143: imports an exported file (a bundle or a single config)
    into the caller's own configs. A config whose uid is already there is
    replaced; a new one whose name is taken is renamed "Name (2)"."""
    _require_rate_limit(request)
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_IMPORT_BYTES:
        raise api_error(413, "too_large", "That file is too large to import")
    return run_import(session, user.id, document)


@router.get("/{config_id}", response_model=SplitConfigOut)
def get_split_config(
    config_id: str, user: CurrentUser, session: Annotated[Session, Depends(db_session)]
) -> SplitConfigOut:
    visible = library.visible_config(session, user.id, config_id)
    if visible is None:
        raise api_error(404, "not_found", "Split config not found")
    return config_out(visible)


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
    to confirm and retry (see docs/SPLIT-CONFIGS-PLAN.md §3/§5.4). Only own
    configs are ever matched: a template's name is free to reuse."""
    _require_rate_limit(request)
    repo = SqlAlchemySplitConfigRepository(session)
    folder_given = "folder" in body.model_fields_set

    if body.overwrite:
        existing = repo.get_by_name_for_user(user.id, body.name)
        if existing is not None:
            existing.plan = _plan_to_json(body.plan)
            if folder_given:
                existing.folder = body.folder
            existing.updated_at = datetime.now(UTC)
            session.flush()
            return _own_out(existing)

    now = datetime.now(UTC)
    config = SplitConfig(
        user_id=user.id,
        name=body.name,
        plan=_plan_to_json(body.plan),
        folder=body.folder,
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
    return _own_out(config)


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
    if config.read_only:
        raise _read_only_error()

    if body.name is not None and body.name != config.name:
        collision = repo.get_by_name_for_user(user.id, body.name)
        if collision is not None and collision.id != config.id:
            raise api_error(
                409, "name_conflict", f"A split config named '{body.name}' already exists."
            )
        config.name = body.name
    if body.plan is not None:
        config.plan = _plan_to_json(body.plan)
    if "folder" in body.model_fields_set:
        config.folder = files.clean_folder(body.folder)
    config.updated_at = datetime.now(UTC)
    session.flush()
    return _own_out(config)


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
    if config.read_only:
        raise _read_only_error()
    repo.delete(config)
