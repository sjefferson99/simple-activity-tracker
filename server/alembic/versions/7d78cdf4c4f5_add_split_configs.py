"""add split configs

Revision ID: 7d78cdf4c4f5
Revises: 3f19b6fcb456
Create Date: 2026-09-22 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

import app.models.types
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7d78cdf4c4f5"
down_revision: str | Sequence[str] | None = "3f19b6fcb456"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "split_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("created_at", app.models.types.TZDateTime(timezone=True), nullable=False),
        sa.Column("updated_at", app.models.types.TZDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_split_configs_user_id_name"),
    )
    op.create_index(op.f("ix_split_configs_user_id"), "split_configs", ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_split_configs_user_id"), table_name="split_configs")
    op.drop_table("split_configs")
