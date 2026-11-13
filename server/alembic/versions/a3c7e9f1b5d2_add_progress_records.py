"""add elapsed/gain columns and activity_best_efforts (issue #190)

Revision ID: a3c7e9f1b5d2
Revises: e8a4c2f7d913
Create Date: 2026-11-13 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3c7e9f1b5d2"
down_revision: str | Sequence[str] | None = "e8a4c2f7d913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("activity_analyses", sa.Column("elapsed_seconds", sa.Float(), nullable=True))
    op.add_column("activity_analyses", sa.Column("elevation_gain_m", sa.Float(), nullable=True))
    op.create_table(
        "activity_best_efforts",
        sa.Column("activity_id", sa.String(length=36), nullable=False),
        sa.Column("distance_m", sa.Float(), nullable=False),
        sa.Column("duration_s", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["activity_id"], ["activities.id"]),
        sa.PrimaryKeyConstraint("activity_id", "distance_m"),
    )
    # Backfill from the stored results, so the Progress page works straight
    # after migrating even with auto-reanalyze off. With it on (the default),
    # the ANALYSIS_VERSION 14 bump then rewrites every row with the longer
    # best-effort distance list anyway.
    op.execute(
        "UPDATE activity_analyses "
        "SET elapsed_seconds = json_extract(result, '$.elapsed_seconds'), "
        "    elevation_gain_m = json_extract(result, '$.elevation.gain_m') "
        "WHERE result IS NOT NULL AND status = 'done'"
    )
    op.execute(
        "INSERT INTO activity_best_efforts (activity_id, distance_m, duration_s) "
        "SELECT a.activity_id, "
        "       json_extract(e.value, '$.distance_meters'), "
        "       json_extract(e.value, '$.duration_seconds') "
        "FROM activity_analyses a, json_each(a.result, '$.best_efforts') e "
        "WHERE a.result IS NOT NULL AND a.status = 'done' "
        "  AND json_extract(e.value, '$.distance_meters') IS NOT NULL "
        "  AND json_extract(e.value, '$.duration_seconds') IS NOT NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("activity_best_efforts")
    op.drop_column("activity_analyses", "elevation_gain_m")
    op.drop_column("activity_analyses", "elapsed_seconds")
