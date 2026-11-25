from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base
from app.models.types import TZDateTime
from app.models.user import _new_uuid


class SplitConfig(Base):
    """A named, reusable split plan (issue #126), owned by one user — the
    server-side counterpart of mobile's SplitPlanController state, except
    there can be many of these per user and they are only ever copied into
    the phone's single "current plan" on selection, never live-linked to it
    (see docs/SPLIT-CONFIGS-PLAN.md O5). Distinct from Activity.split_plan,
    which is a per-activity snapshot taken at upload time and never
    references a SplitConfig row.

    A row with source_id set is a read-only *template* synced from one of
    the user's split repos (issue #143, docs/SPLIT-LIBRARY-PLAN.md). Templates
    don't take part in name uniqueness, so saving an own config can never
    overwrite one."""

    __tablename__ = "split_configs"
    __table_args__ = (
        # Partial indexes: own configs are unique by name and by uid per
        # user; templates by uid per source.
        Index(
            "uq_split_configs_own_name",
            "user_id",
            "name",
            unique=True,
            sqlite_where=text("source_id IS NULL"),
            postgresql_where=text("source_id IS NULL"),
        ),
        Index(
            "uq_split_configs_own_uid",
            "user_id",
            "uid",
            unique=True,
            sqlite_where=text("source_id IS NULL"),
            postgresql_where=text("source_id IS NULL"),
        ),
        Index(
            "uq_split_configs_source_uid",
            "source_id",
            "uid",
            unique=True,
            sqlite_where=text("source_id IS NOT NULL"),
            postgresql_where=text("source_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Same JSON shape as Activity.split_plan / app.api.v1.schemas.SplitPlanOut
    # / app.analysis.gpx_parser.SplitPlanData — split_type, split_value,
    # rolling_target_mps, custom_splits, targets_as. Validated at the API
    # boundary (app.split_configs.validation), not by a DB constraint, same
    # convention as Activity's own untyped JSON columns.
    plan: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    # Stable identity across instances (issue #143): carried by export files
    # and repo files, so an import or a sync updates the same config rather
    # than adding another. Rows from before #143 were backfilled with their id.
    uid: Mapped[str] = mapped_column(String(36), nullable=False, default=_new_uuid)
    # Own configs: free-text folder or None. Templates: the folder's path
    # inside the repo ("" for a file straight under the repo's path).
    folder: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("split_sources.id"), nullable=True, index=True
    )
    # Templates only: the file the template came from, for messages.
    source_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    @property
    def read_only(self) -> bool:
        return self.source_id is not None
