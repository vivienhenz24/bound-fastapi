from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


class TTSModel(Base):
    __tablename__ = "tts_models"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4, index=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    training_job_id: Mapped[UUID | None] = mapped_column(
        Uuid, nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_s3_key: Mapped[str] = mapped_column(String(512), nullable=False)
    model_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    base_model: Mapped[str] = mapped_column(
        String(255), default="Qwen3-TTS-12Hz-1.7B-Base", nullable=False
    )

    # Training metadata
    training_epochs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    training_samples: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_loss: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Usage tracking
    inference_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    user = relationship("User", back_populates="tts_models")
    training_job = relationship(
        "TTSTrainingJob",
        back_populates="model",
        foreign_keys="TTSTrainingJob.model_id",
        uselist=False,
    )
