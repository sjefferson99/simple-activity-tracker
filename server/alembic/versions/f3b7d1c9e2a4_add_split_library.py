"""add split library: sources, folders, template configs (issue #143)

Revision ID: f3b7d1c9e2a4
Revises: c4e8a2d6f0b1
Create Date: 2026-11-24 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

import app.models.types
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3b7d1c9e2a4"
down_revision: str | Sequence[str] | None = "c4e8a2d6f0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OWN = sa.text("source_id IS NULL")
_TEMPLATE = sa.text("source_id IS NOT NULL")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "split_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("host_kind", sa.String(length=20), nullable=False),
        sa.Column("ref", sa.String(length=200), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("token", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("last_synced_at", app.models.types.TZDateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", app.models.types.TZDateTime(timezone=True), nullable=True),
        sa.Column("last_commit", sa.String(length=100), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("created_at", app.models.types.TZDateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_split_sources_user_id"), "split_sources", ["user_id"], unique=False)
    op.create_table(
        "split_source_folders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("folder", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["split_sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "folder", name="uq_split_source_folders"),
    )
    op.create_index(
        op.f("ix_split_source_folders_source_id"),
        "split_source_folders",
        ["source_id"],
        unique=False,
    )

    with op.batch_alter_table("split_configs") as batch_op:
        batch_op.add_column(sa.Column("uid", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("folder", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("source_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("source_path", sa.String(length=500), nullable=True))
        batch_op.drop_constraint("uq_split_configs_user_id_name", type_="unique")
        batch_op.create_foreign_key(
            "fk_split_configs_source_id", "split_sources", ["source_id"], ["id"]
        )
    # Every existing config keeps its id as its uid.
    op.execute("UPDATE split_configs SET uid = id WHERE uid IS NULL")
    with op.batch_alter_table("split_configs") as batch_op:
        batch_op.alter_column("uid", existing_type=sa.String(length=36), nullable=False)
    op.create_index(
        op.f("ix_split_configs_source_id"), "split_configs", ["source_id"], unique=False
    )
    op.create_index(
        "uq_split_configs_own_name",
        "split_configs",
        ["user_id", "name"],
        unique=True,
        sqlite_where=_OWN,
        postgresql_where=_OWN,
    )
    op.create_index(
        "uq_split_configs_own_uid",
        "split_configs",
        ["user_id", "uid"],
        unique=True,
        sqlite_where=_OWN,
        postgresql_where=_OWN,
    )
    op.create_index(
        "uq_split_configs_source_uid",
        "split_configs",
        ["source_id", "uid"],
        unique=True,
        sqlite_where=_TEMPLATE,
        postgresql_where=_TEMPLATE,
    )


def downgrade() -> None:
    """Downgrade schema. Templates go: they can be synced again."""
    op.execute("DELETE FROM split_configs WHERE source_id IS NOT NULL")
    op.drop_index("uq_split_configs_source_uid", table_name="split_configs")
    op.drop_index("uq_split_configs_own_uid", table_name="split_configs")
    op.drop_index("uq_split_configs_own_name", table_name="split_configs")
    op.drop_index(op.f("ix_split_configs_source_id"), table_name="split_configs")
    with op.batch_alter_table("split_configs") as batch_op:
        batch_op.drop_constraint("fk_split_configs_source_id", type_="foreignkey")
        batch_op.drop_column("source_path")
        batch_op.drop_column("source_id")
        batch_op.drop_column("folder")
        batch_op.drop_column("uid")
        batch_op.create_unique_constraint("uq_split_configs_user_id_name", ["user_id", "name"])
    op.drop_index(op.f("ix_split_source_folders_source_id"), table_name="split_source_folders")
    op.drop_table("split_source_folders")
    op.drop_index(op.f("ix_split_sources_user_id"), table_name="split_sources")
    op.drop_table("split_sources")
