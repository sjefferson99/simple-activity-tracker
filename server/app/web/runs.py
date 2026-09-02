from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request, Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.deps import db_session
from app.models.run import Run
from app.models.run_analysis import AnalysisStatus, RunAnalysis
from app.repositories.run_analyses import SqlAlchemyRunAnalysisRepository
from app.repositories.runs import SqlAlchemyRunRepository
from app.storage.blob_store import LocalFileBlobStore
from app.web.deps import WebUser, require_htmx_header
from app.web.templating import templates

router = APIRouter(tags=["web"], include_in_schema=False)


def _run_view(run: Run, analysis: RunAnalysis | None) -> dict[str, Any]:
    """Shapes a Run + RunAnalysis pair the way run_detail.html expects —
    mirrors app.api.v1.runs._run_out()/_analysis_out() but as a plain dict
    for template access rather than a Pydantic model."""
    if analysis is None or analysis.status == AnalysisStatus.pending:
        analysis_view: dict[str, Any] = {"status": "pending", "result": None}
    elif analysis.status == AnalysisStatus.failed:
        analysis_view = {"status": "failed", "result": None}
    else:
        analysis_view = {"status": "done", "result": analysis.result}
    return {
        "id": run.id,
        "title": run.title,
        "notes": run.notes,
        "started_at": run.started_at,
        "ended_at": run.ended_at,
        "client_summary": run.client_summary,
        "analysis": analysis_view,
    }


@router.get("/")
def run_list(
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    cursor: str | None = None,
) -> Response:
    page = SqlAlchemyRunRepository(session).list_for_user(user.id, limit=20, cursor=cursor)
    context = {
        "user": user,
        "runs": page.runs,
        "next_cursor": page.next_cursor,
    }
    if request.headers.get("hx-request") == "true":
        return templates.TemplateResponse(request, "partials/run_list_items.html", context)
    return templates.TemplateResponse(request, "runs_list.html", context)


@router.get("/runs/{run_id}")
def run_detail(
    run_id: str,
    request: Request,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    run = SqlAlchemyRunRepository(session).get_by_id_for_user(user.id, run_id)
    if run is None:
        return templates.TemplateResponse(
            request, "not_found.html", {"user": user}, status_code=404
        )
    analysis = SqlAlchemyRunAnalysisRepository(session).get_by_run_id(run.id)
    return templates.TemplateResponse(
        request, "run_detail.html", {"user": user, "run": _run_view(run, analysis)}
    )


@router.patch("/runs/{run_id}", dependencies=[Depends(require_htmx_header)])
def run_patch(
    run_id: str,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
    title: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
) -> Response:
    runs = SqlAlchemyRunRepository(session)
    run = runs.get_by_id_for_user(user.id, run_id)
    if run is None:
        return Response(status_code=404)
    run.title = title.strip() or None
    run.notes = notes.strip() or None
    run.updated_at = datetime.now(UTC)
    return Response(status_code=200, headers={"HX-Refresh": "true"})


@router.delete("/runs/{run_id}", dependencies=[Depends(require_htmx_header)])
def run_delete(
    run_id: str,
    user: WebUser,
    session: Annotated[Session, Depends(db_session)],
) -> Response:
    runs = SqlAlchemyRunRepository(session)
    run = runs.get_by_id_for_user(user.id, run_id)
    if run is None:
        return Response(status_code=404)

    analyses = SqlAlchemyRunAnalysisRepository(session)
    analysis = analyses.get_by_run_id(run.id)
    if analysis is not None:
        analyses.delete(analysis)
        # See app/api/v1/runs.py:delete_run — no relationship() means the
        # analysis delete must be flushed before the run delete.
        session.flush()

    LocalFileBlobStore(Path(get_settings().data_dir)).delete(run.gpx_blob_key)
    runs.delete(run)
    return Response(status_code=200, headers={"HX-Redirect": "/"})
