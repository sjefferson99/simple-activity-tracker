"""add device_name to activities

Revision ID: eeb9278a9b34
Revises: a75d9580f809
Create Date: 2026-09-05 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "eeb9278a9b34"
down_revision: str | Sequence[str] | None = "a75d9580f809"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("activities", sa.Column("device_name", sa.String(length=200), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("activities", "device_name")
