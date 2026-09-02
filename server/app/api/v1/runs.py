import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.analysis.gpx_parser import GpxParseError, parse_gpx
from app.analysis.v1 import ANALYSIS_VERSION, AnalyzerV1
from app.api.v1.errors import api_error
from app.api.v1.schemas import (
    AnalysisOut,
    RunListItem,
    RunListResponse,
    RunOut,
    RunPatchRequest,
    RunSummary,
    TrackOut,
    TrackPointOut,
)
from app.auth.current_user import CurrentUser
from app.config import get_settings
from app.deps import db_session
from app.models.run import Run
from app.models.run_analysis import AnalysisStatus, RunAnalysis
from app.repositories.run_analyses import SqlAlchemyRunAnalysisRepository
from app.repositories.runs import SqlAlchemyRunRepository
from app.storage.blob_store import LocalFileBlobStore

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


def _blob_store() -> LocalFileBlobStore:
    return LocalFileBlobStore(Path(get_settings().data_dir))


def _run_out(run: Run, analysis: RunAnalysis | None) -> RunOut:
    return RunOut(
        id=run.id,
        client_run_id=run.client_run_id,
        started_at=run.started_at,
        ended_at=run.ended_at,
        title=run.title,
        notes=run.notes,
        client_summary=run.client_summary,
        source_platform=run.source_platform,
        source_app_version=run.source_app_version,
        created_at=run.created_at,
        updated_at=run.updated_at,
        analysis=_analysis_out(analysis),
    )


def _analysis_out(analysis: RunAnalysis | None) -> AnalysisOut:
    if analysis is None or analysis.status == AnalysisStatus.pending:
        return AnalysisOut(status="pending")
    if analysis.status == AnalysisStatus.failed:
        return AnalysisOut(status="failed")
    return AnalysisOut(status="done", result=analysis.result)


@router.get("", response_model=RunListResponse)
def list_runs(
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> RunListResponse:
    page = SqlAlchemyRunRepository(session).list_for_user(user.id, limit=limit, cursor=cursor)
    items = [
        RunListItem(
            id=run.id,
            started_at=run.started_at,
            ended_at=run.ended_at,
            title=run.title,
            distance_meters=run.client_summary.get("distance_meters", 0.0),
            moving_seconds=run.client_summary.get("moving_seconds", 0.0),
        )
        for run in page.runs
    ]
    return RunListResponse(runs=items, next_cursor=page.next_cursor)


@router.post("", response_model=RunOut, status_code=201)
def upload_run(
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
    response: Response,
    summary: Annotated[str, Form()],
    gpx: Annotated[UploadFile, File()],
) -> RunOut:
    try:
        summary_model = RunSummary.model_validate_json(summary)
    except ValidationError as exc:
        raise api_error(400, "invalid_summary", str(exc)) from exc

    runs = SqlAlchemyRunRepository(session)
    analyses = SqlAlchemyRunAnalysisRepository(session)

    existing = runs.get_by_client_run_id(user.id, summary_model.client_run_id)
    if existing is not None:
        response.status_code = 200
        return _run_out(existing, analyses.get_by_run_id(existing.id))

    settings = get_settings()
    gpx_bytes = gpx.file.read(settings.max_gpx_bytes + 1)
    if len(gpx_bytes) > settings.max_gpx_bytes:
        raise api_error(
            413, "gpx_too_large", f"GPX file exceeds the {settings.max_gpx_bytes}-byte limit"
        )

    try:
        track = parse_gpx(gpx_bytes)
    except GpxParseError as exc:
        raise api_error(400, "invalid_gpx", str(exc)) from exc

    blob_key = _blob_store().put(user.id, gpx_bytes)

    now = datetime.now(UTC)
    run = Run(
        user_id=user.id,
        client_run_id=summary_model.client_run_id,
        started_at=summary_model.started_at,
        ended_at=summary_model.ended_at,
        client_summary=json.loads(summary),
        gpx_blob_key=blob_key,
        gpx_sha256=hashlib.sha256(gpx_bytes).hexdigest(),
        gpx_bytes=len(gpx_bytes),
        source_platform=summary_model.source.platform,
        source_app_version=summary_model.source.app_version,
        created_at=now,
        updated_at=now,
    )
    runs.add(run)
    session.flush()

    try:
        result = AnalyzerV1().analyze(track)
        analysis = RunAnalysis(
            run_id=run.id,
            analysis_version=ANALYSIS_VERSION,
            status=AnalysisStatus.done,
            result=result,
            computed_at=datetime.now(UTC),
        )
    except Exception as exc:  # analysis failure must never fail the upload
        analysis = RunAnalysis(
            run_id=run.id,
            analysis_version=ANALYSIS_VERSION,
            status=AnalysisStatus.failed,
            error=str(exc),
            computed_at=datetime.now(UTC),
        )
    analyses.add(analysis)
    session.flush()

    return _run_out(run, analysis)


@router.get("/{run_id}", response_model=RunOut)
def get_run(
    run_id: str, user: CurrentUser, session: Annotated[Session, Depends(db_session)]
) -> RunOut:
    run = SqlAlchemyRunRepository(session).get_by_id_for_user(user.id, run_id)
    if run is None:
        raise api_error(404, "not_found", "Run not found")
    analysis = SqlAlchemyRunAnalysisRepository(session).get_by_run_id(run.id)
    return _run_out(run, analysis)


@router.patch("/{run_id}", response_model=RunOut)
def patch_run(
    run_id: str,
    body: RunPatchRequest,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
) -> RunOut:
    run = SqlAlchemyRunRepository(session).get_by_id_for_user(user.id, run_id)
    if run is None:
        raise api_error(404, "not_found", "Run not found")
    if body.title is not None:
        run.title = body.title
    if body.notes is not None:
        run.notes = body.notes
    run.updated_at = datetime.now(UTC)
    analysis = SqlAlchemyRunAnalysisRepository(session).get_by_run_id(run.id)
    return _run_out(run, analysis)


@router.delete("/{run_id}", status_code=204)
def delete_run(
    run_id: str, user: CurrentUser, session: Annotated[Session, Depends(db_session)]
) -> None:
    runs = SqlAlchemyRunRepository(session)
    run = runs.get_by_id_for_user(user.id, run_id)
    if run is None:
        raise api_error(404, "not_found", "Run not found")

    analysis = SqlAlchemyRunAnalysisRepository(session).get_by_run_id(run.id)
    if analysis is not None:
        SqlAlchemyRunAnalysisRepository(session).delete(analysis)
        # Without a configured relationship(), SQLAlchemy's unit-of-work has
        # no FK dependency graph between Run and RunAnalysis, so it can't be
        # trusted to order two session.delete() calls correctly on flush —
        # flushing the analysis delete now guarantees it happens first.
        session.flush()

    _blob_store().delete(run.gpx_blob_key)
    runs.delete(run)


@router.get("/{run_id}/gpx")
def download_gpx(
    run_id: str, user: CurrentUser, session: Annotated[Session, Depends(db_session)]
) -> Response:
    run = SqlAlchemyRunRepository(session).get_by_id_for_user(user.id, run_id)
    if run is None:
        raise api_error(404, "not_found", "Run not found")
    data = _blob_store().get(run.gpx_blob_key)
    filename = f"{run.started_at.date().isoformat()}.gpx"
    return Response(
        content=data,
        media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{run_id}/analysis", response_model=AnalysisOut)
def get_analysis(
    run_id: str,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
    response: Response,
) -> AnalysisOut:
    run = SqlAlchemyRunRepository(session).get_by_id_for_user(user.id, run_id)
    if run is None:
        raise api_error(404, "not_found", "Run not found")
    analysis = SqlAlchemyRunAnalysisRepository(session).get_by_run_id(run.id)
    out = _analysis_out(analysis)
    if out.status != "done":
        response.status_code = 202
    return out


@router.get("/{run_id}/track", response_model=TrackOut)
def get_track(
    run_id: str,
    user: CurrentUser,
    session: Annotated[Session, Depends(db_session)],
    max_points: Annotated[int, Query(ge=1, le=20000)] = 2000,
) -> TrackOut:
    run = SqlAlchemyRunRepository(session).get_by_id_for_user(user.id, run_id)
    if run is None:
        raise api_error(404, "not_found", "Run not found")

    data = _blob_store().get(run.gpx_blob_key)
    try:
        track = parse_gpx(data)
    except GpxParseError:
        return TrackOut(segments=[])

    out_segments: list[list[TrackPointOut]] = []
    for segment in track.segments:
        points = segment.points
        stride = max(1, -(-len(points) // max_points))
        start_time = track.segments[0].points[0].time
        sampled = points[::stride]
        if sampled[-1] is not points[-1]:
            sampled.append(points[-1])
        out_segments.append(
            [
                TrackPointOut(
                    lat=p.lat, lon=p.lon, ele=p.ele, t=(p.time - start_time).total_seconds()
                )
                for p in sampled
            ]
        )
    return TrackOut(segments=out_segments)
