from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.tts_dataset import DatasetStatus, TranscriptType


# ============================================================================
# Dataset Schemas
# ============================================================================


class DatasetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    transcript_type: TranscriptType = TranscriptType.TEXT


class DatasetUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None


class DatasetResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    description: str | None
    audio_s3_key: str
    transcript_s3_key: str
    transcript_type: str
    status: str
    segment_count: int | None
    total_duration_seconds: float | None
    training_data_s3_key: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DatasetListResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    transcript_type: str
    status: str
    segment_count: int | None
    total_duration_seconds: float | None
    created_at: datetime

    model_config = {"from_attributes": True}
