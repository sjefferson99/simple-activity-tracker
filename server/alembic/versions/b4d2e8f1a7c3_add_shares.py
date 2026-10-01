"""add user and activity shares

Revision ID: b4d2e8f1a7c3
Revises: 7d78cdf4c4f5
Create Date: 2026-10-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4d2e8f1a7c3"
down_revision: str | Sequence[str] | None = "7d78cdf4c4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "user_shares",
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("viewer_id", sa.String(length=36), nullable=False),
        sa.Column("can_view_live", sa.Boolean(), nullable=False),
        sa.Column("can_view_history", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("owner_id <> viewer_id", name="ck_user_shares_not_self"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["viewer_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("owner_id", "viewer_id"),
    )
    op.create_index("ix_user_shares_viewer_id", "user_shares", ["viewer_id"])
    op.create_table(
        "activity_shares",
        sa.Column("activity_id", sa.String(length=36), nullable=False),
        sa.Column("viewer_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"]),
        sa.ForeignKeyConstraint(["viewer_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("activity_id", "viewer_id"),
    )
    op.create_index("ix_activity_shares_viewer_id", "activity_shares", ["viewer_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_activity_shares_viewer_id", table_name="activity_shares")
    op.drop_table("activity_shares")
    op.drop_index("ix_user_shares_viewer_id", table_name="user_shares")
    op.drop_table("user_shares")
