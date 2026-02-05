"""add tts datasets table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-03 19:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add TTS datasets table."""
    op.create_table(
        "tts_datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("audio_s3_key", sa.String(length=512), nullable=False),
        sa.Column("transcript_s3_key", sa.String(length=512), nullable=False),
        sa.Column(
            "transcript_type",
            sa.String(length=10),
            nullable=False,
            server_default="text",
        ),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="pending"
        ),
        sa.Column("segment_count", sa.Integer(), nullable=True),
        sa.Column("total_duration_seconds", sa.Float(), nullable=True),
        sa.Column("training_data_s3_key", sa.String(length=512), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tts_datasets_id"), "tts_datasets", ["id"], unique=False)
    op.create_index(
        op.f("ix_tts_datasets_user_id"), "tts_datasets", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_tts_datasets_status"), "tts_datasets", ["status"], unique=False
    )


def downgrade() -> None:
    """Remove TTS datasets table."""
    op.drop_index(op.f("ix_tts_datasets_status"), table_name="tts_datasets")
    op.drop_index(op.f("ix_tts_datasets_user_id"), table_name="tts_datasets")
    op.drop_index(op.f("ix_tts_datasets_id"), table_name="tts_datasets")
    op.drop_table("tts_datasets")
