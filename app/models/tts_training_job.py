from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


class JobStatus(str, Enum):
    QUEUED = "queued"
    PREPARING = "preparing"
    TRAINING = "training"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TTSTrainingJob(Base):
    __tablename__ = "tts_training_jobs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4, index=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tts_datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=JobStatus.QUEUED.value, nullable=False, index=True
    )
    runpod_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    queue_position: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Training hyperparameters
    epochs: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    learning_rate: Mapped[float] = mapped_column(Float, default=1e-5, nullable=False)
    batch_size: Mapped[int] = mapped_column(Integer, default=4, nullable=False)

    # Training progress
    current_epoch: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    loss: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Result
    model_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("tts_models.id", ondelete="SET NULL"), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Relationships
    user = relationship("User", back_populates="tts_training_jobs")
    dataset = relationship("TTSDataset", back_populates="training_jobs")
    model = relationship("TTSModel", back_populates="training_job", foreign_keys=[model_id])
