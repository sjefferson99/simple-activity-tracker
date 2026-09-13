import enum
from datetime import datetime
from typing import Any

from sqlalchemy import Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base
from app.models.types import TZDateTime


class AnalysisStatus(enum.StrEnum):
    pending = "pending"
    done = "done"
    failed = "failed"


class ActivityAnalysis(Base):
    __tablename__ = "activity_analyses"

    activity_id: Mapped[str] = mapped_column(ForeignKey("activities.id"), primary_key=True)
    analysis_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[AnalysisStatus] = mapped_column(
        Enum(AnalysisStatus, native_enum=False), nullable=False
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # Denormalized copies of result["distance_meters"]/["moving_seconds"] (see
    # issue #75) so the activity list page can sort/display them with a plain
    # column instead of a JSON extract on every request. 0 for pending/failed
    # analyses — kept in sync by app.analysis.v1.distance_and_duration_from_result()
    # at every place that sets `result` (upload/import, reanalyze CLI).
    distance_meters: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    moving_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    computed_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    # Cached output of sample_track() at DEFAULT_MAX_POINTS, computed once at
    # upload/reanalyze time instead of re-parsing the full GPX blob on every
    # map view — see R8 in docs/SERVER-PRODUCTION-PLAN.md. Null for rows
    # analyzed before this column existed, or when analysis failed; the
    # track endpoint falls back to parsing on the fly in either case.
    track: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
