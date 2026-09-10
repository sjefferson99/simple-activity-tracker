from datetime import datetime

from sqlalchemy import Column, ForeignKey, Index, String, Table, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import TZDateTime
from app.models.user import _new_uuid

# Plain Table (not a mapped association class) since no column is needed on
# the association itself — see Activity.tags below.
activity_tags = Table(
    "activity_tags",
    Base.metadata,
    Column("activity_id", ForeignKey("activities.id"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id"), primary_key=True),
    Index("ix_activity_tags_tag_id", "tag_id"),
)


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_tags_user_id_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    # Tags are private per-user — no cross-user sharing/global vocabulary,
    # matching every other per-user resource in this app. Comparisons for
    # get-or-create are case-insensitive (see SqlAlchemyTagRepository), but
    # the original casing the user/importer typed is stored verbatim.
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
