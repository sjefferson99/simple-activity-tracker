"""add start end coordinates to activity analyses

Revision ID: 5a6b3dd72c96
Revises: 0aff3bc612d3
Create Date: 2026-09-14 00:32:33.038314

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5a6b3dd72c96"
down_revision: str | Sequence[str] | None = "0aff3bc612d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("activity_analyses", sa.Column("start_lat", sa.Float(), nullable=True))
    op.add_column("activity_analyses", sa.Column("start_lon", sa.Float(), nullable=True))
    op.add_column("activity_analyses", sa.Column("end_lat", sa.Float(), nullable=True))
    op.add_column("activity_analyses", sa.Column("end_lon", sa.Float(), nullable=True))
    # Backfill from the R8 downsampled-track cache (app/analysis/track_sampling.py),
    # which always keeps each segment's first and last point — so the very
    # first point of the first segment and the very last point of the last
    # segment are the run's start/finish. SQLite's `[#-1]` last-element path
    # syntax (confirmed available on both this project's dev SQLite and the
    # container's) picks the last segment and, within it, the last point,
    # without needing to know how many segments/points there are.
    #
    # Only rows with a non-null `track` (i.e. analyzed after R8 shipped) and
    # status='done' are covered — everything else (pre-R8 rows, and any
    # pending/failed row) is left null and picked up by
    # `simple-activity-tracker-server reanalyze --all`, same as this
    # migration's precedent in 0aff3bc612d3.
    #
    # No index is added on these columns: the activity list query is already
    # scoped by user_id via the activities table (ix_activities_user_started_at),
    # and per-user activity counts don't justify one for a proximity filter —
    # same reasoning as this migration's sibling text-search LIKE queries.
    op.execute(
        "UPDATE activity_analyses "
        "SET start_lat = json_extract(track, '$.segments[0][0].lat'), "
        "    start_lon = json_extract(track, '$.segments[0][0].lon'), "
        "    end_lat = json_extract(track, '$.segments[#-1][#-1].lat'), "
        "    end_lon = json_extract(track, '$.segments[#-1][#-1].lon') "
        "WHERE track IS NOT NULL AND status = 'done'"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("activity_analyses", "end_lon")
    op.drop_column("activity_analyses", "end_lat")
    op.drop_column("activity_analyses", "start_lon")
    op.drop_column("activity_analyses", "start_lat")
