"""add is_virtual to activities (issue #190)

Revision ID: c4e8a2d6f0b1
Revises: a3c7e9f1b5d2
Create Date: 2026-11-13 18:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e8a2d6f0b1"
down_revision: str | Sequence[str] | None = "a3c7e9f1b5d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # No backfill: Strava's own type ("Virtual Ride") was never stored, so
    # existing virtual activities are flagged by their owner on the web page.
    with op.batch_alter_table("activities") as batch_op:
        batch_op.add_column(
            sa.Column("is_virtual", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("activities") as batch_op:
        batch_op.drop_column("is_virtual")
