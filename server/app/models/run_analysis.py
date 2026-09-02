import enum
from datetime import datetime
from typing import Any

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base
from app.models.types import TZDateTime


class AnalysisStatus(enum.StrEnum):
    pending = "pending"
    done = "done"
    failed = "failed"


class RunAnalysis(Base):
    __tablename__ = "run_analyses"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    analysis_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[AnalysisStatus] = mapped_column(
        Enum(AnalysisStatus, native_enum=False), nullable=False
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
