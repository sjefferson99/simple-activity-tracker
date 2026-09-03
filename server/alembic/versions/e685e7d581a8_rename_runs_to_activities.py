"""rename runs to activities, add activity_type

Revision ID: e685e7d581a8
Revises: 0774885df36f
Create Date: 2026-09-03 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e685e7d581a8"
down_revision: str | Sequence[str] | None = "0774885df36f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- runs -> activities ---
    op.rename_table("runs", "activities")

    # SQLite's ALTER TABLE support is limited (no native column rename before
    # very recent SQLite versions via this driver, no drop/rename constraint)
    # — batch_alter_table recreates the table under the hood on SQLite while
    # emitting plain ALTER statements on backends that support them natively.
    #
    # This is deliberately split into two batch_alter_table blocks on
    # "activities", not one: testing this migration's downgrade/upgrade
    # round-trip found that renaming a column *and*, in the same batch
    # block, dropping+recreating a UNIQUE constraint that covers that same
    # (renamed) column silently drops the constraint entirely with no error
    # — the rebuilt table ends up with neither the old nor the new
    # constraint. Doing the column rename in its own block first, then the
    # constraint swap against the now-already-renamed column in a second
    # block, avoids it (confirmed by direct testing against SQLite).
    with op.batch_alter_table("activities", schema=None, recreate="always") as batch_op:
        batch_op.alter_column("client_run_id", new_column_name="client_activity_id")
        # server_default is for the backfill of existing rows only — the
        # SQLAlchemy model declares no server-side default, so new inserts
        # must state activity_type explicitly at the app layer.
        batch_op.add_column(
            sa.Column(
                "activity_type", sa.String(length=20), nullable=False, server_default="running"
            )
        )

    with op.batch_alter_table("activities", schema=None, recreate="always") as batch_op:
        batch_op.drop_constraint("uq_runs_user_client_run_id", type_="unique")
        batch_op.create_unique_constraint(
            "uq_activities_user_client_activity_id", ["user_id", "client_activity_id"]
        )
        batch_op.drop_index("ix_runs_user_started_at")
        batch_op.create_index(
            "ix_activities_user_started_at", ["user_id", "started_at"], unique=False
        )

    # --- run_analyses -> activity_analyses ---
    op.rename_table("run_analyses", "activity_analyses")

    # batch_alter_table reflects the table (FK included) and recreates it
    # under the hood on SQLite, so renaming the FK column here carries the
    # foreign key across automatically — it now simply points at the new
    # "activities" table (renamed above) instead of "runs".
    with op.batch_alter_table("activity_analyses", schema=None, recreate="always") as batch_op:
        batch_op.alter_column("run_id", new_column_name="activity_id")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("activity_analyses", schema=None, recreate="always") as batch_op:
        batch_op.alter_column("activity_id", new_column_name="run_id")

    op.rename_table("activity_analyses", "run_analyses")

    # See the comment in upgrade() — split across two batch blocks for the
    # same reason: renaming client_activity_id back to client_run_id in the
    # same block as swapping the unique constraint that covers it silently
    # loses the constraint.
    with op.batch_alter_table("activities", schema=None, recreate="always") as batch_op:
        batch_op.drop_index("ix_activities_user_started_at")
        batch_op.create_index("ix_runs_user_started_at", ["user_id", "started_at"], unique=False)
        batch_op.drop_constraint("uq_activities_user_client_activity_id", type_="unique")
        batch_op.create_unique_constraint(
            "uq_runs_user_client_run_id", ["user_id", "client_activity_id"]
        )

    with op.batch_alter_table("activities", schema=None, recreate="always") as batch_op:
        batch_op.drop_column("activity_type")
        batch_op.alter_column("client_activity_id", new_column_name="client_run_id")

    op.rename_table("activities", "runs")
