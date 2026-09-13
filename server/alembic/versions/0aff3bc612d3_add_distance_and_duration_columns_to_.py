"""add distance and duration columns to activity_analyses

Revision ID: 0aff3bc612d3
Revises: c1a9b2d4e6f0
Create Date: 2026-09-13 19:54:05.475875

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0aff3bc612d3"
down_revision: str | Sequence[str] | None = "c1a9b2d4e6f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "activity_analyses",
        sa.Column("distance_meters", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "activity_analyses",
        sa.Column("moving_seconds", sa.Float(), nullable=False, server_default="0"),
    )
    # Backfill existing rows from the JSON result blob (SQLite's json_extract
    # works the same way on the Postgres-compatible subset this project uses
    # elsewhere) — pending/failed rows have no result and keep the column
    # default of 0, same as the "no distance yet" case the web UI already
    # has to handle for a genuinely fresh upload.
    op.execute(
        "UPDATE activity_analyses "
        "SET distance_meters = COALESCE(json_extract(result, '$.distance_meters'), 0), "
        "    moving_seconds = COALESCE(json_extract(result, '$.moving_seconds'), 0) "
        "WHERE result IS NOT NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("activity_analyses", "moving_seconds")
    op.drop_column("activity_analyses", "distance_meters")
