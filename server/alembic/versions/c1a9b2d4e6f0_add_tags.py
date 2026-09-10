"""add tags

Revision ID: c1a9b2d4e6f0
Revises: f02d59257d57
Create Date: 2026-09-10 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1a9b2d4e6f0"
down_revision: str | Sequence[str] | None = "f02d59257d57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "tags",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_tags_user_id_name"),
    )
    op.create_table(
        "activity_tags",
        sa.Column("activity_id", sa.String(length=36), nullable=False),
        sa.Column("tag_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"]),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"]),
        sa.PrimaryKeyConstraint("activity_id", "tag_id"),
    )
    op.create_index("ix_activity_tags_tag_id", "activity_tags", ["tag_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_activity_tags_tag_id", table_name="activity_tags")
    op.drop_table("activity_tags")
    op.drop_table("tags")
