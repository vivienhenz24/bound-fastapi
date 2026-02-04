"""add tts tables

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
    """Add TTS datasets, training jobs, and models tables."""
    # Create tts_models first (referenced by training_jobs)
    op.create_table(
        "tts_models",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("training_job_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("model_s3_key", sa.String(length=512), nullable=False),
        sa.Column("model_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column(
            "base_model",
            sa.String(length=255),
            nullable=False,
            server_default="Qwen3-TTS-12Hz-1.7B-Base",
        ),
        sa.Column("training_epochs", sa.Integer(), nullable=True),
        sa.Column("training_samples", sa.Integer(), nullable=True),
        sa.Column("final_loss", sa.Float(), nullable=True),
        sa.Column("inference_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tts_models_id"), "tts_models", ["id"], unique=False)
    op.create_index(
        op.f("ix_tts_models_user_id"), "tts_models", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_tts_models_training_job_id"),
        "tts_models",
        ["training_job_id"],
        unique=False,
    )

    # Create tts_datasets
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

    # Create tts_training_jobs
    op.create_table(
        "tts_training_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="queued"
        ),
        sa.Column("runpod_job_id", sa.String(length=255), nullable=True),
        sa.Column("queue_position", sa.Integer(), nullable=True),
        sa.Column("epochs", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("learning_rate", sa.Float(), nullable=False, server_default="0.00001"),
        sa.Column("batch_size", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("current_epoch", sa.Integer(), nullable=True),
        sa.Column("current_step", sa.Integer(), nullable=True),
        sa.Column("total_steps", sa.Integer(), nullable=True),
        sa.Column("loss", sa.Float(), nullable=True),
        sa.Column("model_id", sa.Uuid(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dataset_id"], ["tts_datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_id"], ["tts_models.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_tts_training_jobs_id"), "tts_training_jobs", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_tts_training_jobs_user_id"),
        "tts_training_jobs",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tts_training_jobs_dataset_id"),
        "tts_training_jobs",
        ["dataset_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tts_training_jobs_status"),
        "tts_training_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tts_training_jobs_runpod_job_id"),
        "tts_training_jobs",
        ["runpod_job_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove TTS tables."""
    op.drop_index(
        op.f("ix_tts_training_jobs_runpod_job_id"), table_name="tts_training_jobs"
    )
    op.drop_index(
        op.f("ix_tts_training_jobs_status"), table_name="tts_training_jobs"
    )
    op.drop_index(
        op.f("ix_tts_training_jobs_dataset_id"), table_name="tts_training_jobs"
    )
    op.drop_index(
        op.f("ix_tts_training_jobs_user_id"), table_name="tts_training_jobs"
    )
    op.drop_index(op.f("ix_tts_training_jobs_id"), table_name="tts_training_jobs")
    op.drop_table("tts_training_jobs")

    op.drop_index(op.f("ix_tts_datasets_status"), table_name="tts_datasets")
    op.drop_index(op.f("ix_tts_datasets_user_id"), table_name="tts_datasets")
    op.drop_index(op.f("ix_tts_datasets_id"), table_name="tts_datasets")
    op.drop_table("tts_datasets")

    op.drop_index(
        op.f("ix_tts_models_training_job_id"), table_name="tts_models"
    )
    op.drop_index(op.f("ix_tts_models_user_id"), table_name="tts_models")
    op.drop_index(op.f("ix_tts_models_id"), table_name="tts_models")
    op.drop_table("tts_models")
