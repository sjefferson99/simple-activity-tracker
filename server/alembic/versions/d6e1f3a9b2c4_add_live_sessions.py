"""add live sessions, live points and live sharing pause

Revision ID: d6e1f3a9b2c4
Revises: b4d2e8f1a7c3
Create Date: 2026-10-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d6e1f3a9b2c4"
down_revision: str | Sequence[str] | None = "b4d2e8f1a7c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "live_sharing_paused", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
    op.create_table(
        "live_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("client_activity_id", sa.String(length=36), nullable=False),
        sa.Column("activity_type", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("split_plan", sa.JSON(), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("latest_metrics", sa.JSON(), nullable=True),
        sa.Column("next_index", sa.Integer(), nullable=False),
        sa.Column("last_update_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activity_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "client_activity_id", name="uq_live_sessions_user_client_activity_id"
        ),
    )
    op.create_index("ix_live_sessions_last_update_at", "live_sessions", ["last_update_at"])
    op.create_table(
        "live_points",
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("t", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("ele", sa.Float(), nullable=True),
        sa.Column("accuracy", sa.Float(), nullable=True),
        sa.Column("speed", sa.Float(), nullable=True),
        sa.Column("segment", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["live_sessions.id"]),
        sa.PrimaryKeyConstraint("session_id", "idx"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("live_points")
    op.drop_index("ix_live_sessions_last_update_at", table_name="live_sessions")
    op.drop_table("live_sessions")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("live_sharing_paused")
