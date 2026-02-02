"""update timestamps to use server defaults

Revision ID: 5005f4425ead
Revises: 4f16b994612b
Create Date: 2026-01-28 17:30:05.724523

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5005f4425ead"
down_revision: str | Sequence[str] | None = "4f16b994612b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add server defaults for timestamp columns
    op.alter_column("users", "created_at", server_default=sa.text("now()"))
    op.alter_column("users", "updated_at", server_default=sa.text("now()"))
    op.alter_column("refresh_tokens", "created_at", server_default=sa.text("now()"))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove server defaults
    op.alter_column("users", "created_at", server_default=None)
    op.alter_column("users", "updated_at", server_default=None)
    op.alter_column("refresh_tokens", "created_at", server_default=None)
