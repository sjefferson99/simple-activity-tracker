"""add split plan to activities

Revision ID: 3f19b6fcb456
Revises: 5a6b3dd72c96
Create Date: 2026-09-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f19b6fcb456"
down_revision: str | Sequence[str] | None = "5a6b3dd72c96"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("activities", sa.Column("split_plan", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("activities", "split_plan")
