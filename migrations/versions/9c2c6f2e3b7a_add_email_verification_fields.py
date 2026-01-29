"""add email verification fields to users

Revision ID: 9c2c6f2e3b7a
Revises: 70be4eb2dab8
Create Date: 2026-01-29 10:12:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9c2c6f2e3b7a"
down_revision: Union[str, Sequence[str], None] = "70be4eb2dab8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "users", sa.Column("email_verification_token_hash", sa.Text(), nullable=True)
    )
    op.add_column(
        "users", sa.Column("email_verification_expires_at", sa.DateTime(), nullable=True)
    )
    op.create_index(
        op.f("ix_users_email_verification_token_hash"),
        "users",
        ["email_verification_token_hash"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_users_email_verification_token_hash"), table_name="users")
    op.drop_column("users", "email_verification_expires_at")
    op.drop_column("users", "email_verification_token_hash")
