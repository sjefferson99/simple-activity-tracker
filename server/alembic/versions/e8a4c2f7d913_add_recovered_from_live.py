"""add recovered_from_live to activities

Revision ID: e8a4c2f7d913
Revises: d6e1f3a9b2c4
Create Date: 2026-10-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8a4c2f7d913"
down_revision: str | Sequence[str] | None = "d6e1f3a9b2c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("activities") as batch_op:
        batch_op.add_column(
            sa.Column(
                "recovered_from_live", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("activities") as batch_op:
        batch_op.drop_column("recovered_from_live")
