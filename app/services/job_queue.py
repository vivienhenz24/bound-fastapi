"""Job queue service for managing TTS training jobs.

Handles:
- Job creation and queue management
- Background polling of RunPod job status
- Updating job progress and completion
- Creating model records on job completion
"""

import asyncio
import logging
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.models.tts_dataset import DatasetStatus, TTSDataset
from app.models.tts_model import TTSModel
from app.models.tts_training_job import JobStatus, TTSTrainingJob
from app.services import runpod_service
from app.services.runpod_service import (
    RunPodJobStatus,
    TrainingJobInput,
)

logger = logging.getLogger(__name__)

# Background task handle
_polling_task: asyncio.Task | None = None
POLL_INTERVAL_SECONDS = 10


async def create_training_job(
    db: AsyncSession,
    user_id: UUID,
    dataset_id: UUID,
    name: str,
    epochs: int,
    learning_rate: float,
    batch_size: int,
) -> TTSTrainingJob:
    """Create a new training job and submit to RunPod.

    Args:
        db: Database session
        user_id: User ID
        dataset_id: Dataset ID (must be in READY status)
        name: Job name
        epochs: Number of training epochs
        learning_rate: Learning rate
        batch_size: Batch size

    Returns:
        Created TTSTrainingJob

    Raises:
        ValueError: If dataset is not ready for training
    """
    # Verify dataset exists and is ready
    result = await db.execute(
        select(TTSDataset).where(
            TTSDataset.id == dataset_id,
            TTSDataset.user_id == user_id,
        )
    )
    dataset = result.scalar_one_or_none()

    if not dataset:
        raise ValueError("Dataset not found")

    if dataset.status != DatasetStatus.READY.value:
        raise ValueError(f"Dataset is not ready for training (status: {dataset.status})")

    if not dataset.training_data_s3_key:
        raise ValueError("Dataset has no training data")

    # Calculate queue position
    queue_result = await db.execute(
        select(TTSTrainingJob).where(
            TTSTrainingJob.status.in_([JobStatus.QUEUED.value, JobStatus.PREPARING.value])
        )
    )
    queued_jobs = queue_result.scalars().all()
    queue_position = len(queued_jobs) + 1

    # Create job record
    job = TTSTrainingJob(
        id=uuid4(),
        user_id=user_id,
        dataset_id=dataset_id,
        name=name,
        status=JobStatus.QUEUED.value,
        queue_position=queue_position,
        epochs=epochs,
        learning_rate=learning_rate,
        batch_size=batch_size,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Submit to RunPod
    output_model_key = f"users/{user_id}/models/{uuid4()}/model.safetensors"
    job_input = TrainingJobInput(
        dataset_s3_key=dataset.audio_s3_key,
        training_data_s3_key=dataset.training_data_s3_key,
        output_model_s3_key=output_model_key,
        epochs=epochs,
        learning_rate=learning_rate,
        batch_size=batch_size,
    )

    runpod_result = await runpod_service.submit_training_job(job_input)

    if runpod_result.error:
        # Mark job as failed
        job.status = JobStatus.FAILED.value
        job.error_message = runpod_result.error
        await db.commit()
        raise ValueError(f"Failed to submit job to RunPod: {runpod_result.error}")

    # Update job with RunPod ID
    job.runpod_job_id = runpod_result.job_id
    job.status = JobStatus.PREPARING.value
    await db.commit()
    await db.refresh(job)

    logger.info(f"Created training job {job.id} with RunPod ID {runpod_result.job_id}")

    return job


async def cancel_training_job(db: AsyncSession, job_id: UUID, user_id: UUID) -> bool:
    """Cancel a training job.

    Args:
        db: Database session
        job_id: Job ID
        user_id: User ID (for authorization)

    Returns:
        True if cancellation was successful
    """
    result = await db.execute(
        select(TTSTrainingJob).where(
            TTSTrainingJob.id == job_id,
            TTSTrainingJob.user_id == user_id,
        )
    )
    job = result.scalar_one_or_none()

    if not job:
        raise ValueError("Job not found")

    if job.status in [JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value]:
        raise ValueError(f"Cannot cancel job in {job.status} status")

    # Cancel on RunPod if job ID exists
    if job.runpod_job_id:
        await runpod_service.cancel_job("training", job.runpod_job_id)

    # Update job status
    job.status = JobStatus.CANCELLED.value
    job.completed_at = datetime.utcnow()
    await db.commit()

    logger.info(f"Cancelled training job {job_id}")

    return True


async def _update_job_from_runpod(
    db: AsyncSession, job: TTSTrainingJob, runpod_result: runpod_service.RunPodJobResult
) -> None:
    """Update job record based on RunPod status.

    Args:
        db: Database session
        job: Job to update
        runpod_result: Status from RunPod
    """
    if runpod_result.status == RunPodJobStatus.IN_PROGRESS:
        if job.status != JobStatus.TRAINING.value:
            job.status = JobStatus.TRAINING.value
            job.started_at = datetime.utcnow()
            job.queue_position = None

        # Update progress if available in output
        if runpod_result.output:
            output = runpod_result.output
            if "current_epoch" in output:
                job.current_epoch = output["current_epoch"]
            if "current_step" in output:
                job.current_step = output["current_step"]
            if "total_steps" in output:
                job.total_steps = output["total_steps"]
            if "loss" in output:
                job.loss = output["loss"]

    elif runpod_result.status == RunPodJobStatus.COMPLETED:
        job.status = JobStatus.COMPLETED.value
        job.completed_at = datetime.utcnow()
        job.queue_position = None

        # Extract model info from output
        if runpod_result.output:
            output = runpod_result.output
            model_s3_key = output.get("model_s3_key")

            if model_s3_key:
                # Create model record
                model = TTSModel(
                    id=uuid4(),
                    user_id=job.user_id,
                    training_job_id=job.id,
                    name=f"{job.name} Model",
                    model_s3_key=model_s3_key,
                    model_size_bytes=output.get("model_size_bytes"),
                    training_epochs=job.epochs,
                    training_samples=output.get("training_samples"),
                    final_loss=output.get("final_loss") or job.loss,
                )
                db.add(model)
                await db.flush()

                job.model_id = model.id

                logger.info(f"Created model {model.id} from job {job.id}")

    elif runpod_result.status in [RunPodJobStatus.FAILED, RunPodJobStatus.TIMED_OUT]:
        job.status = JobStatus.FAILED.value
        job.error_message = runpod_result.error or "Job failed"
        job.completed_at = datetime.utcnow()
        job.queue_position = None

    elif runpod_result.status == RunPodJobStatus.CANCELLED:
        job.status = JobStatus.CANCELLED.value
        job.completed_at = datetime.utcnow()
        job.queue_position = None

    await db.commit()


async def _poll_active_jobs() -> None:
    """Poll RunPod for status of all active jobs."""
    async with async_session() as db:
        # Get all active jobs
        result = await db.execute(
            select(TTSTrainingJob).where(
                TTSTrainingJob.status.in_([
                    JobStatus.QUEUED.value,
                    JobStatus.PREPARING.value,
                    JobStatus.TRAINING.value,
                ]),
                TTSTrainingJob.runpod_job_id.isnot(None),
            )
        )
        jobs = result.scalars().all()

        for job in jobs:
            try:
                runpod_result = await runpod_service.get_job_status(
                    "training", job.runpod_job_id
                )
                await _update_job_from_runpod(db, job, runpod_result)

            except Exception as e:
                logger.exception(f"Error polling job {job.id}: {e}")

        # Update queue positions for queued jobs
        queued_result = await db.execute(
            select(TTSTrainingJob)
            .where(TTSTrainingJob.status == JobStatus.QUEUED.value)
            .order_by(TTSTrainingJob.created_at)
        )
        queued_jobs = queued_result.scalars().all()

        for i, job in enumerate(queued_jobs, start=1):
            if job.queue_position != i:
                job.queue_position = i

        await db.commit()


async def _polling_loop() -> None:
    """Background polling loop."""
    logger.info("Starting job status polling loop")

    while True:
        try:
            await _poll_active_jobs()
        except Exception as e:
            logger.exception(f"Error in polling loop: {e}")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


def start_polling() -> None:
    """Start the background polling task."""
    global _polling_task

    if _polling_task is None or _polling_task.done():
        _polling_task = asyncio.create_task(_polling_loop())
        logger.info("Started job status polling task")


def stop_polling() -> None:
    """Stop the background polling task."""
    global _polling_task

    if _polling_task and not _polling_task.done():
        _polling_task.cancel()
        logger.info("Stopped job status polling task")


async def get_queue_status(db: AsyncSession) -> dict:
    """Get global queue status.

    Returns:
        Dict with queue statistics
    """
    # Count jobs by status
    result = await db.execute(
        select(TTSTrainingJob.status, TTSTrainingJob.id).where(
            TTSTrainingJob.status.in_([
                JobStatus.QUEUED.value,
                JobStatus.PREPARING.value,
                JobStatus.TRAINING.value,
            ])
        )
    )
    jobs = result.all()

    queued_count = sum(1 for s, _ in jobs if s == JobStatus.QUEUED.value)
    training_count = sum(
        1 for s, _ in jobs if s in [JobStatus.PREPARING.value, JobStatus.TRAINING.value]
    )

    return {
        "total_queued": queued_count,
        "total_training": training_count,
        "total_active": len(jobs),
    }
