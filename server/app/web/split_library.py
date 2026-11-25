"""The split library page (issue #143, docs/SPLIT-LIBRARY-PLAN.md §2.4): the
user's split repos with their folder switches, adding/editing/removing a
repo, syncing, and importing/exporting split config files. Same operations
as /api/v1/split-sources, through app.split_library directly (the web layer
never calls its own JSON API)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.auth.rate_limit import account_action_rate_limiter, split_fetch_rate_limiter
from app.config import get_settings
from app.deps import db_session
from app.models.split_source import SplitSource, SplitSourceFolder
from app.split_library import files, library
from app.web.deps import WebUser, require_htmx_header
from app.web.templating import templates

router = APIRouter(tags=["web"], include_in_schema=False)

_MAX_IMPORT_BYTES = 2 * 1024 * 1024


def _sources_context(
    session: Session,
    user: object,
    user_id: str,
    *,
    message: str | None = None,
    error: str | None = None,
    form: dict[str, str] | None = None,
) -> dict[str, object]:
    library.ensure_default_source(session, user_id)
    session.flush()
    sources = library.list_sources(session, user_id)
    ids = [s.id for s in sources]
    return {
        "user": user,
        "sources": sources,
        "folders": library.folders_for(session, ids),
        "counts": library.template_counts(session, ids),
        "can_add": get_settings().split_sources_allow_user_repos,
        "message": message,
        "error": error,
        "form": form or {"url": "", "host_kind": "", "ref": "main", "path": "splits", "name": ""},
        "own_folders": library.own_folders(session, user_id),
    }


def _render_sources(
    request: Request, context: dict[str, object], status_code: int = 200
) -> Response:
    return templates.TemplateResponse(
        request, "partials/split_library_sources.html", context, status_code=status_code
    )


def _sync_message(source: SplitSource, result: library.SyncResult) -> tuple[str | None, str | None]:
    if result.busy:
        return None, f"{source.name}: a sync is already running"
    if not result.ok:
        return None, f"{source.name}: {result.error}"
    parts = []
    if result.added:
        parts.append(f"{result.added} added")
    if result.updated:
        parts.append(f"{result.updated} updated")
    if result.removed:
        parts.append(f"{result.removed} removed")
    summary = ", ".join(parts) if parts else "no changes"
    return f"{source.name} synced: {summary}.", None


@router.get("/split-configs/library")
def split_library_page(
    request: Request, user: WebUser, session: Annotated[Session, Depends(db_session)]
) -> Response:
    return templates.TemplateResponse(
        request, "split_library.html", _sources_context(session, user, user.id)
    )


@router.post("/split-configs/library/sources", dependencies=[Depends(require_htmx_header)])
def add_split_source(
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    url: Annotated[str, Form()] = "",
    host_kind: Annotated[str, Form()] = "",
    ref: Annotated[str, Form()] = "main",
    path: Annotated[str, Form()] = "splits",
    name: Annotated[str, Form()] = "",
    token: Annotated[str, Form()] = "",
) -> Response:
    form = {"url": url, "host_kind": host_kind, "ref": ref, "path": path, "name": name}
    if not split_fetch_rate_limiter.allow(f"user:{user.id}"):
        return _render_sources(
            request,
            _sources_context(
                session, user, user.id, error="Too many repo fetches, try again shortly", form=form
            ),
            status_code=429,
        )
    try:
        source = library.add_source(
            session,
            user.id,
            url=url[:500],
            host_kind=host_kind or None,
            ref=ref[:200],
            path=path[:500],
            name=name[:200] or None,
            token=token[:1000] or None,
        )
    except library.SourceInputError as exc:
        return _render_sources(
            request, _sources_context(session, user, user.id, error=str(exc), form=form), 400
        )
    message, error = _sync_message(source, library.sync_source(session, source))
    return _render_sources(
        request, _sources_context(session, user, user.id, message=message, error=error)
    )


def _source_or_none(session: Session, user_id: str, source_id: str) -> SplitSource | None:
    return library.get_source(session, user_id, source_id)


@router.post(
    "/split-configs/library/sources/{source_id}/sync",
    dependencies=[Depends(require_htmx_header)],
)
def sync_split_source(
    source_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    source = _source_or_none(session, user.id, source_id)
    if source is None:
        return Response(status_code=404)
    if not split_fetch_rate_limiter.allow(f"user:{user.id}"):
        return _render_sources(
            request,
            _sources_context(
                session, user, user.id, error="Too many repo fetches, try again shortly"
            ),
            status_code=429,
        )
    message, error = _sync_message(source, library.sync_source(session, source))
    return _render_sources(
        request, _sources_context(session, user, user.id, message=message, error=error)
    )


@router.patch(
    "/split-configs/library/sources/{source_id}", dependencies=[Depends(require_htmx_header)]
)
def update_split_source(
    source_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    enabled: Annotated[str | None, Form()] = None,
    name: Annotated[str | None, Form()] = None,
    ref: Annotated[str | None, Form()] = None,
    path: Annotated[str | None, Form()] = None,
    token: Annotated[str | None, Form()] = None,
    clear_token: Annotated[bool, Form()] = False,
) -> Response:
    """The on/off switch (any source), or the edit form (not the default
    source, whose location comes from the server's settings)."""
    source = _source_or_none(session, user.id, source_id)
    if source is None:
        return Response(status_code=404)
    if enabled is not None:
        source.enabled = enabled == "true"
    editing = any(v is not None for v in (name, ref, path, token)) or clear_token
    if editing and source.is_default:
        return Response(status_code=403)
    if editing:
        try:
            _, _, new_ref, new_path = library.validate_source_input(
                url=source.url,
                host_kind=source.host_kind,
                ref=(ref if ref is not None else source.ref)[:200],
                path=(path if path is not None else source.path)[:500],
            )
        except library.SourceInputError as exc:
            return _render_sources(
                request, _sources_context(session, user, user.id, error=str(exc)), 400
            )
        if name is not None and name.strip():
            source.name = name.strip()[:200]
        if (new_ref, new_path) != (source.ref, source.path):
            source.ref, source.path = new_ref, new_path
            source.last_attempt_at = None
        if clear_token:
            source.token = None
        elif token is not None and token.strip():
            source.token = token.strip()[:1000]
    session.flush()
    message = (
        f"{source.name} saved. Sync it to fetch from the new location."
        if (editing and source.last_attempt_at is None)
        else None
    )
    return _render_sources(request, _sources_context(session, user, user.id, message=message))


@router.delete(
    "/split-configs/library/sources/{source_id}", dependencies=[Depends(require_htmx_header)]
)
def remove_split_source(
    source_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    source = _source_or_none(session, user.id, source_id)
    if source is None:
        return Response(status_code=404)
    if source.is_default:
        return Response(status_code=403)
    name = source.name
    library.delete_source(session, source)
    return _render_sources(
        request, _sources_context(session, user, user.id, message=f"Removed {name}.")
    )


@router.patch(
    "/split-configs/library/folders/{folder_id}", dependencies=[Depends(require_htmx_header)]
)
def toggle_split_folder(
    folder_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    enabled: Annotated[str, Form()] = "true",
) -> Response:
    folder = session.get(SplitSourceFolder, folder_id)
    if folder is None or _source_or_none(session, user.id, folder.source_id) is None:
        return Response(status_code=404)
    folder.enabled = enabled == "true"
    session.flush()
    return _render_sources(request, _sources_context(session, user, user.id))


@router.post("/split-configs/import", dependencies=[Depends(require_htmx_header)])
async def import_split_configs_file(
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    file: UploadFile,
) -> Response:
    """Imports an exported split config file into the user's own configs."""

    def result(context: dict[str, object], status_code: int = 200) -> Response:
        return templates.TemplateResponse(
            request,
            "partials/split_import_result.html",
            {"user": user, **context},
            status_code=status_code,
        )

    client_ip = request.client.host if request.client else "unknown"
    if not account_action_rate_limiter.allow(f"ip:{client_ip}"):
        return result({"error": "Too many attempts, try again shortly"}, 429)
    raw = await file.read(_MAX_IMPORT_BYTES + 1)
    if len(raw) > _MAX_IMPORT_BYTES:
        return result({"error": "That file is too large to import"}, 413)
    try:
        parsed, errors = files.parse_document(raw)
    except files.DocumentError as exc:
        return result({"error": f"Couldn't import {file.filename or 'that file'}: {exc}"}, 400)
    outcome = library.import_configs(session, user.id, parsed)
    return result({"outcome": outcome, "errors": errors})
