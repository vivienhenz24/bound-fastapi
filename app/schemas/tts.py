from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.tts_dataset import DatasetStatus, TranscriptType
from app.models.tts_training_job import JobStatus


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


# ============================================================================
# Training Job Schemas
# ============================================================================


class JobCreate(BaseModel):
    dataset_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    epochs: int = Field(default=3, ge=1, le=20)
    learning_rate: float = Field(default=1e-5, ge=1e-7, le=1e-3)
    batch_size: int = Field(default=4, ge=1, le=32)


class JobUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)


class JobProgress(BaseModel):
    current_epoch: int | None
    current_step: int | None
    total_steps: int | None
    loss: float | None


class JobResponse(BaseModel):
    id: UUID
    user_id: UUID
    dataset_id: UUID
    name: str
    status: str
    runpod_job_id: str | None
    queue_position: int | None
    epochs: int
    learning_rate: float
    batch_size: int
    current_epoch: int | None
    current_step: int | None
    total_steps: int | None
    loss: float | None
    model_id: UUID | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    id: UUID
    name: str
    status: str
    queue_position: int | None
    epochs: int
    current_epoch: int | None
    loss: float | None
    model_id: UUID | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class QueueStatusResponse(BaseModel):
    total_queued: int
    total_training: int
    jobs: list[JobListResponse]


# ============================================================================
# Model Schemas
# ============================================================================


class ModelCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class ModelUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    is_public: bool | None = None


class ModelResponse(BaseModel):
    id: UUID
    user_id: UUID
    training_job_id: UUID | None
    name: str
    description: str | None
    model_s3_key: str
    model_size_bytes: int | None
    base_model: str
    training_epochs: int | None
    training_samples: int | None
    final_loss: float | None
    inference_count: int
    is_public: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ModelListResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    base_model: str
    training_epochs: int | None
    final_loss: float | None
    inference_count: int
    is_public: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ModelDownloadResponse(BaseModel):
    download_url: str
    expires_in_seconds: int = 3600


# ============================================================================
# Inference Schemas
# ============================================================================


class InferenceRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    speaker_id: str | None = None


class InferenceResponse(BaseModel):
    audio_url: str
    duration_seconds: float | None = None
    expires_in_seconds: int = 3600


class InferenceJobStatus(BaseModel):
    status: str
    audio_url: str | None = None
    error_message: str | None = None
