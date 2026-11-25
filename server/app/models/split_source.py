from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.models.base import Base
from app.models.types import TZDateTime
from app.models.user import _new_uuid


class SplitSource(Base):
    """A git repo a user subscribes to for split templates (issue #143,
    docs/SPLIT-LIBRARY-PLAN.md). Per user: everyone gets the project's own
    repo as their default source, and can add others, including private
    ones with an access token."""

    __tablename__ = "split_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Repo web URL as the user gave it, e.g. https://github.com/owner/repo.
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    host_kind: Mapped[str] = mapped_column(String(20), nullable=False)  # github/gitlab/gitea
    ref: Mapped[str] = mapped_column(String(200), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    # Access token for a private repo. Never returned by an API or page;
    # only `has_token` is.
    token: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    last_commit: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Files skipped on the last sync, as "path: reason" strings.
    warnings: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)


class SplitSourceFolder(Base):
    """One folder of a source's templates, with the user's on/off switch.
    Created by sync (new folders start on) and removed when the folder
    disappears from the repo."""

    __tablename__ = "split_source_folders"
    __table_args__ = (UniqueConstraint("source_id", "folder", name="uq_split_source_folders"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("split_sources.id"), nullable=False, index=True
    )
    folder: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
