"""cache downsampled track on activity_analyses

Revision ID: a75d9580f809
Revises: c9e96b644fd5
Create Date: 2026-09-05 14:59:39.756671

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a75d9580f809"
down_revision: str | Sequence[str] | None = "c9e96b644fd5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("activity_analyses", sa.Column("track", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("activity_analyses", "track")
