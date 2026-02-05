from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from sqlalchemy import Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


class DatasetStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class TranscriptType(str, Enum):
    TEXT = "text"
    SRT = "srt"


class TTSDataset(Base):
    __tablename__ = "tts_datasets"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4, index=True)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_s3_key: Mapped[str] = mapped_column(String(512), nullable=False)
    transcript_s3_key: Mapped[str] = mapped_column(String(512), nullable=False)
    transcript_type: Mapped[str] = mapped_column(
        String(10), default=TranscriptType.TEXT.value, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default=DatasetStatus.PENDING.value, nullable=False, index=True
    )
    segment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_data_s3_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    user = relationship("User", back_populates="tts_datasets")
