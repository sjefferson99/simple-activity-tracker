"""baseline

Revision ID: 761ac6b41e1e
Revises:
Create Date: 2026-09-02 21:48:33.051046

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "761ac6b41e1e"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
