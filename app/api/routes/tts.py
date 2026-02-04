"""TTS API routes for datasets, training jobs, models, and inference."""

from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_active_user
from app.db.session import get_db
from app.models.tts_dataset import DatasetStatus, TTSDataset, TranscriptType
from app.models.tts_model import TTSModel
from app.models.tts_training_job import JobStatus, TTSTrainingJob
from app.models.user import User
from app.schemas.tts import (
    DatasetCreate,
    DatasetListResponse,
    DatasetResponse,
    DatasetUpdate,
    InferenceRequest,
    InferenceResponse,
    JobCreate,
    JobListResponse,
    JobResponse,
    ModelDownloadResponse,
    ModelListResponse,
    ModelResponse,
    ModelUpdate,
    QueueStatusResponse,
)
from app.services import audio_processor, job_queue, s3, tts_inference

router = APIRouter(prefix="/tts", tags=["tts"])


# ============================================================================
# Dataset Endpoints
# ============================================================================


@router.post("/datasets", response_model=DatasetResponse, status_code=status.HTTP_201_CREATED)
async def create_dataset(
    audio: UploadFile = File(...),
    transcript: UploadFile = File(...),
    name: str = Form(...),
    description: str | None = Form(None),
    transcript_type: str = Form("text"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload audio and transcript files to create a new dataset."""
    # Validate transcript type
    if transcript_type not in [t.value for t in TranscriptType]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid transcript_type. Must be one of: {[t.value for t in TranscriptType]}",
        )

    # Read and validate audio file
    audio_data = await audio.read()
    is_valid, error = audio_processor.validate_audio_file(audio_data)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error,
        )

    # Read transcript file
    transcript_data = await transcript.read()

    # Create dataset record
    from uuid import uuid4

    dataset_id = uuid4()

    # Upload files to S3
    audio_s3_key = f"users/{current_user.id}/datasets/{dataset_id}/source_audio.wav"
    transcript_ext = "srt" if transcript_type == "srt" else "txt"
    transcript_s3_key = f"users/{current_user.id}/datasets/{dataset_id}/transcript.{transcript_ext}"

    try:
        s3.upload_file(audio_s3_key, audio_data, content_type="audio/wav")
        s3.upload_file(
            transcript_s3_key,
            transcript_data,
            content_type="text/plain" if transcript_type == "text" else "text/srt",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload files: {str(e)}",
        )

    # Create database record
    dataset = TTSDataset(
        id=dataset_id,
        user_id=current_user.id,
        name=name,
        description=description,
        audio_s3_key=audio_s3_key,
        transcript_s3_key=transcript_s3_key,
        transcript_type=transcript_type,
        status=DatasetStatus.PENDING.value,
    )
    db.add(dataset)
    await db.commit()
    await db.refresh(dataset)

    return dataset


@router.get("/datasets", response_model=list[DatasetListResponse])
async def list_datasets(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List all datasets for the current user."""
    result = await db.execute(
        select(TTSDataset)
        .where(TTSDataset.user_id == current_user.id)
        .order_by(TTSDataset.created_at.desc())
    )
    datasets = result.scalars().all()
    return datasets


@router.get("/datasets/{dataset_id}", response_model=DatasetResponse)
async def get_dataset(
    dataset_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific dataset."""
    result = await db.execute(
        select(TTSDataset).where(
            TTSDataset.id == dataset_id,
            TTSDataset.user_id == current_user.id,
        )
    )
    dataset = result.scalar_one_or_none()

    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    return dataset


@router.delete("/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dataset(
    dataset_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a dataset."""
    result = await db.execute(
        select(TTSDataset).where(
            TTSDataset.id == dataset_id,
            TTSDataset.user_id == current_user.id,
        )
    )
    dataset = result.scalar_one_or_none()

    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    # Check if any training jobs are using this dataset
    jobs_result = await db.execute(
        select(TTSTrainingJob).where(
            TTSTrainingJob.dataset_id == dataset_id,
            TTSTrainingJob.status.in_([JobStatus.QUEUED.value, JobStatus.TRAINING.value]),
        )
    )
    active_jobs = jobs_result.scalars().first()

    if active_jobs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete dataset with active training jobs",
        )

    await db.delete(dataset)
    await db.commit()


async def _process_dataset_task(
    user_id: UUID,
    dataset_id: UUID,
    audio_s3_key: str,
    transcript_s3_key: str,
    transcript_type: str,
):
    """Background task to process dataset."""
    from app.db.session import async_session

    async with async_session() as db:
        result = await db.execute(
            select(TTSDataset).where(TTSDataset.id == dataset_id)
        )
        dataset = result.scalar_one_or_none()

        if not dataset:
            return

        try:
            # Update status to processing
            dataset.status = DatasetStatus.PROCESSING.value
            await db.commit()

            # Process the dataset
            processing_result = await audio_processor.process_dataset(
                user_id=user_id,
                dataset_id=dataset_id,
                audio_s3_key=audio_s3_key,
                transcript_s3_key=transcript_s3_key,
                transcript_type=transcript_type,
            )

            if processing_result.error:
                dataset.status = DatasetStatus.FAILED.value
                dataset.error_message = processing_result.error
            else:
                dataset.status = DatasetStatus.READY.value
                dataset.segment_count = len(processing_result.segments)
                dataset.total_duration_seconds = processing_result.total_duration_seconds
                dataset.training_data_s3_key = f"users/{user_id}/datasets/{dataset_id}/training_data.jsonl"

            await db.commit()

        except Exception as e:
            dataset.status = DatasetStatus.FAILED.value
            dataset.error_message = str(e)
            await db.commit()


@router.post("/datasets/{dataset_id}/process", response_model=DatasetResponse)
async def process_dataset(
    dataset_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger processing (segmentation) of a dataset."""
    result = await db.execute(
        select(TTSDataset).where(
            TTSDataset.id == dataset_id,
            TTSDataset.user_id == current_user.id,
        )
    )
    dataset = result.scalar_one_or_none()

    if not dataset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    if dataset.status not in [DatasetStatus.PENDING.value, DatasetStatus.FAILED.value]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Dataset cannot be processed in current status: {dataset.status}",
        )

    # Start background processing
    background_tasks.add_task(
        _process_dataset_task,
        user_id=current_user.id,
        dataset_id=dataset_id,
        audio_s3_key=dataset.audio_s3_key,
        transcript_s3_key=dataset.transcript_s3_key,
        transcript_type=dataset.transcript_type,
    )

    # Update status
    dataset.status = DatasetStatus.PROCESSING.value
    dataset.error_message = None
    await db.commit()
    await db.refresh(dataset)

    return dataset


# ============================================================================
# Training Job Endpoints
# ============================================================================


@router.post("/jobs", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    job_data: JobCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new training job."""
    try:
        job = await job_queue.create_training_job(
            db=db,
            user_id=current_user.id,
            dataset_id=job_data.dataset_id,
            name=job_data.name,
            epochs=job_data.epochs,
            learning_rate=job_data.learning_rate,
            batch_size=job_data.batch_size,
        )
        return job
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/jobs", response_model=list[JobListResponse])
async def list_jobs(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List all training jobs for the current user."""
    result = await db.execute(
        select(TTSTrainingJob)
        .where(TTSTrainingJob.user_id == current_user.id)
        .order_by(TTSTrainingJob.created_at.desc())
    )
    jobs = result.scalars().all()
    return jobs


@router.get("/jobs/queue", response_model=QueueStatusResponse)
async def get_queue_status(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get global queue status."""
    queue_status = await job_queue.get_queue_status(db)

    # Get user's queued/training jobs
    result = await db.execute(
        select(TTSTrainingJob)
        .where(
            TTSTrainingJob.user_id == current_user.id,
            TTSTrainingJob.status.in_([
                JobStatus.QUEUED.value,
                JobStatus.PREPARING.value,
                JobStatus.TRAINING.value,
            ]),
        )
        .order_by(TTSTrainingJob.queue_position, TTSTrainingJob.created_at)
    )
    jobs = result.scalars().all()

    return QueueStatusResponse(
        total_queued=queue_status["total_queued"],
        total_training=queue_status["total_training"],
        jobs=[JobListResponse.model_validate(j) for j in jobs],
    )


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific training job."""
    result = await db.execute(
        select(TTSTrainingJob).where(
            TTSTrainingJob.id == job_id,
            TTSTrainingJob.user_id == current_user.id,
        )
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    return job


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a training job."""
    try:
        await job_queue.cancel_training_job(db, job_id, current_user.id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    # Refresh and return the job
    result = await db.execute(
        select(TTSTrainingJob).where(TTSTrainingJob.id == job_id)
    )
    job = result.scalar_one()
    return job


# ============================================================================
# Model Endpoints
# ============================================================================


@router.get("/models", response_model=list[ModelListResponse])
async def list_models(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List all models for the current user."""
    result = await db.execute(
        select(TTSModel)
        .where(
            TTSModel.user_id == current_user.id,
            TTSModel.is_deleted == False,  # noqa: E712
        )
        .order_by(TTSModel.created_at.desc())
    )
    models = result.scalars().all()
    return models


@router.get("/models/{model_id}", response_model=ModelResponse)
async def get_model(
    model_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific model."""
    result = await db.execute(
        select(TTSModel).where(
            TTSModel.id == model_id,
            TTSModel.is_deleted == False,  # noqa: E712
        )
    )
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )

    # Check authorization
    if model.user_id != current_user.id and not model.is_public:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Model not accessible",
        )

    return model


@router.patch("/models/{model_id}", response_model=ModelResponse)
async def update_model(
    model_id: UUID,
    model_data: ModelUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update model name/description."""
    result = await db.execute(
        select(TTSModel).where(
            TTSModel.id == model_id,
            TTSModel.user_id == current_user.id,
            TTSModel.is_deleted == False,  # noqa: E712
        )
    )
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )

    # Update fields
    if model_data.name is not None:
        model.name = model_data.name
    if model_data.description is not None:
        model.description = model_data.description
    if model_data.is_public is not None:
        model.is_public = model_data.is_public

    await db.commit()
    await db.refresh(model)

    return model


@router.delete("/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    model_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft delete a model."""
    result = await db.execute(
        select(TTSModel).where(
            TTSModel.id == model_id,
            TTSModel.user_id == current_user.id,
            TTSModel.is_deleted == False,  # noqa: E712
        )
    )
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )

    model.is_deleted = True
    await db.commit()


@router.get("/models/{model_id}/download", response_model=ModelDownloadResponse)
async def get_model_download_url(
    model_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a presigned URL to download a model."""
    result = await db.execute(
        select(TTSModel).where(
            TTSModel.id == model_id,
            TTSModel.is_deleted == False,  # noqa: E712
        )
    )
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )

    # Check authorization
    if model.user_id != current_user.id and not model.is_public:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Model not accessible",
        )

    try:
        download_url = s3.generate_presigned_url(model.model_s3_key, expiration=3600)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate download URL: {str(e)}",
        )

    return ModelDownloadResponse(download_url=download_url)


# ============================================================================
# Inference Endpoint
# ============================================================================


@router.post("/models/{model_id}/infer", response_model=InferenceResponse)
async def infer(
    model_id: UUID,
    request: InferenceRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate speech from text using a model."""
    result = await tts_inference.generate_speech(
        db=db,
        model_id=model_id,
        user_id=current_user.id,
        text=request.text,
        speaker_id=request.speaker_id,
    )

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.error or "Inference failed",
        )

    return InferenceResponse(
        audio_url=result.audio_url,
        duration_seconds=result.duration_seconds,
    )
