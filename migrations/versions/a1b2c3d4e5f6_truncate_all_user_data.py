"""truncate all user data

Revision ID: a1b2c3d4e5f6
Revises: 40e2259b7701
Create Date: 2026-02-03 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "40e2259b7701"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Truncate all user data from the database."""
    # TRUNCATE with CASCADE will handle foreign key relationships
    # This deletes refresh_tokens and users in one statement
    op.execute("TRUNCATE TABLE users CASCADE")


def downgrade() -> None:
    """Downgrade - data cannot be restored."""
    # Data deletion is irreversible - this is intentionally a no-op
    pass
