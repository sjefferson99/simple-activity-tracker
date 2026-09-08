"""add split preference to activities

Revision ID: f02d59257d57
Revises: eeb9278a9b34
Create Date: 2026-09-08 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f02d59257d57"
down_revision: str | Sequence[str] | None = "eeb9278a9b34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("activities", sa.Column("split_type", sa.String(length=20), nullable=True))
    op.add_column("activities", sa.Column("split_value", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("activities", "split_value")
    op.drop_column("activities", "split_type")
