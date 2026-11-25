"""Split template repos a user subscribes to (issue #143,
docs/SPLIT-LIBRARY-PLAN.md §2.3, API level 4): list them with their folders,
add/edit/remove one, switch folders on and off, and sync now."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.errors import api_error
from app.api.v1.schemas import (
    SplitSourceCreateRequest,
    SplitSourceFolderOut,
    SplitSourceFolderPatchRequest,
    SplitSourceListResponse,
    SplitSourceOut,
    SplitSourcePatchRequest,
    SplitSourceSyncResponse,
)
from app.auth.current_user import CurrentUser
from app.auth.rate_limit import split_fetch_rate_limiter
from app.config import get_settings
from app.deps import db_session
from app.models.split_source import SplitSource, SplitSourceFolder
from app.split_library import library

router = APIRouter(prefix="/api/v1/split-sources", tags=["split-sources"])


def sources_out(session: Session, sources: list[SplitSource]) -> list[SplitSourceOut]:
    ids = [s.id for s in sources]
    folders = library.folders_for(session, ids)
    counts = library.template_counts(session, ids)
    return [
        SplitSourceOut(
            id=s.id,
            name=s.name,
            url=s.url,
            host_kind=s.host_kind,  # type: ignore[arg-type]
            ref=s.ref,
            path=s.path,
            enabled=s.enabled,
            is_default=s.is_default,
            has_token=bool(s.token),
            last_synced_at=s.last_synced_at,
            last_commit=s.last_commit,
            last_error=s.last_error,
            warnings=[str(w) for w in s.warnings or []],
            folders=[
                SplitSourceFolderOut(
                    id=f.id,
                    folder=f.folder,
                    name=f.display_name,
                    description=f.description,
                    enabled=f.enabled,
                    template_count=counts.get((s.id, f.folder), 0),
                )
                for f in folders[s.id]
            ],
        )
        for s in sources
    ]


def _one_out(session: Session, source: SplitSource) -> SplitSourceOut:
    return sources_out(session, [source])[0]


def _require_fetch_budget(user_id: str) -> None:
    if not split_fetch_rate_limiter.allow(f"user:{user_id}"):
        raise api_error(429, "rate_limited", "Too many repo fetches. Try again shortly.")


def _get_or_404(session: Session, user_id: str, source_id: str) -> SplitSource:
    source = library.get_source(session, user_id, source_id)
    if source is None:
        raise api_error(404, "not_found", "Split repo not found")
    return source


@router.get("", response_model=SplitSourceListResponse)
def list_split_sources(
    user: CurrentUser, session: Annotated[Session, Depends(db_session)]
) -> SplitSourceListResponse:
    library.ensure_default_source(session, user.id)
    session.flush()
    return SplitSourceListResponse(
        sources=sources_out(session, library.list_sources(session, user.id)),
        can_add=get_settings().split_sources_allow_user_repos,
    )


@router.post("", response_model=SplitSourceSyncResponse, status_code=201)
def create_split_source(
    body: SplitSourceCreateRequest,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
) -> SplitSourceSyncResponse:
    """Subscribes to a repo and syncs it straight away. A failed first sync
    still keeps the subscription, with the error on it, so the user can
    fix the URL, branch or token and sync again."""
    _require_fetch_budget(user.id)
    try:
        source = library.add_source(
            session,
            user.id,
            url=body.url,
            host_kind=body.host_kind,
            ref=body.ref,
            path=body.path,
            name=body.name,
            token=body.token,
        )
    except library.SourceInputError as exc:
        raise api_error(422, "invalid_source", str(exc)) from exc
    result = library.sync_source(session, source)
    return SplitSourceSyncResponse(
        ok=result.ok,
        added=result.added,
        updated=result.updated,
        removed=result.removed,
        error=result.error,
        source=_one_out(session, source),
    )


@router.patch("/{source_id}", response_model=SplitSourceOut)
def patch_split_source(
    source_id: str,
    body: SplitSourcePatchRequest,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
) -> SplitSourceOut:
    """The default repo's URL, branch and folder come from the server's
    settings, so only its on/off switch can change."""
    source = _get_or_404(session, user.id, source_id)
    changes_location = body.ref is not None or body.path is not None
    if source.is_default and (
        changes_location or body.token is not None or body.clear_token or body.name is not None
    ):
        raise api_error(
            403, "read_only", "The default repo can only be switched on or off on this server"
        )
    if body.name is not None and body.name.strip():
        source.name = body.name.strip()
    if changes_location:
        try:
            _, _, ref, path = library.validate_source_input(
                url=source.url,
                host_kind=source.host_kind,
                ref=body.ref if body.ref is not None else source.ref,
                path=body.path if body.path is not None else source.path,
            )
        except library.SourceInputError as exc:
            raise api_error(422, "invalid_source", str(exc)) from exc
        if (ref, path) != (source.ref, source.path):
            source.ref, source.path = ref, path
            # Due again, so the next list picks up the new location.
            source.last_attempt_at = None
    if body.clear_token:
        source.token = None
    elif body.token is not None and body.token.strip():
        source.token = body.token.strip()
    if body.enabled is not None:
        source.enabled = body.enabled
    session.flush()
    return _one_out(session, source)


@router.delete("/{source_id}", status_code=204)
def delete_split_source(
    source_id: str,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
) -> None:
    source = _get_or_404(session, user.id, source_id)
    if source.is_default:
        raise api_error(
            403, "read_only", "The default repo can't be removed; switch it off instead"
        )
    library.delete_source(session, source)


@router.post("/{source_id}/sync", response_model=SplitSourceSyncResponse)
def sync_split_source(
    source_id: str,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
) -> SplitSourceSyncResponse:
    """Fetches the repo now. A failure (host down, bad token) is reported in
    the body with ok=false, not as an HTTP error: the request itself worked."""
    source = _get_or_404(session, user.id, source_id)
    _require_fetch_budget(user.id)
    result = library.sync_source(session, source)
    return SplitSourceSyncResponse(
        ok=result.ok,
        added=result.added,
        updated=result.updated,
        removed=result.removed,
        error=result.error,
        source=_one_out(session, source),
    )


@router.patch("/{source_id}/folders/{folder_id}", response_model=SplitSourceOut)
def patch_split_source_folder(
    source_id: str,
    folder_id: str,
    body: SplitSourceFolderPatchRequest,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
) -> SplitSourceOut:
    """Shows or hides one folder's templates, on the web and every phone."""
    source = _get_or_404(session, user.id, source_id)
    folder = session.get(SplitSourceFolder, folder_id)
    if folder is None or folder.source_id != source.id:
        raise api_error(404, "not_found", "Folder not found")
    folder.enabled = body.enabled
    session.flush()
    return _one_out(session, source)
