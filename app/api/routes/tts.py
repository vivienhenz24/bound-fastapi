"""TTS API routes for dataset management and audio processing."""

from pathlib import Path
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
from app.models.user import User
from app.schemas.tts import (
    DatasetListResponse,
    DatasetResponse,
)
from app.services import audio_processor, s3

router = APIRouter(prefix="/tts", tags=["tts"])


@router.post("/datasets", response_model=DatasetResponse, status_code=status.HTTP_201_CREATED)
async def create_dataset(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    transcript: UploadFile = File(...),
    name: str = Form(...),
    description: str | None = Form(None),
    transcript_type: str = Form("text"),
    auto_process: bool = Form(True),
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
    audio_extension = Path(audio.filename or "").suffix.lower().lstrip(".") or "wav"
    audio_s3_key = (
        f"users/{current_user.id}/datasets/{dataset_id}/source_audio.{audio_extension}"
    )
    transcript_ext = "srt" if transcript_type == "srt" else "txt"
    transcript_s3_key = f"users/{current_user.id}/datasets/{dataset_id}/transcript.{transcript_ext}"

    try:
        audio_content_type = audio.content_type or "application/octet-stream"
        transcript_content_type = (
            "application/x-subrip" if transcript_type == "srt" else "text/plain"
        )
        s3.upload_file(audio_s3_key, audio_data, content_type=audio_content_type)
        s3.upload_file(
            transcript_s3_key,
            transcript_data,
            content_type=transcript_content_type,
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
        status=DatasetStatus.PROCESSING.value
        if auto_process
        else DatasetStatus.PENDING.value,
        error_message=None,
    )
    db.add(dataset)
    await db.commit()
    await db.refresh(dataset)

    if auto_process:
        background_tasks.add_task(
            _process_dataset_task,
            user_id=current_user.id,
            dataset_id=dataset_id,
            audio_s3_key=audio_s3_key,
            transcript_s3_key=transcript_s3_key,
            transcript_type=transcript_type,
        )

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
