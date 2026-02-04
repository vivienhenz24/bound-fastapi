"""TTS inference service for generating speech from text.

Handles:
- Submitting inference requests to RunPod
- Managing audio output storage
- Generating presigned URLs for results
"""

import logging
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tts_model import TTSModel
from app.services import runpod_service, s3
from app.services.runpod_service import InferenceJobInput, RunPodJobStatus

logger = logging.getLogger(__name__)


@dataclass
class InferenceResult:
    """Result of a TTS inference request."""

    success: bool
    audio_s3_key: str | None = None
    audio_url: str | None = None
    duration_seconds: float | None = None
    error: str | None = None


async def generate_speech(
    db: AsyncSession,
    model_id: UUID,
    user_id: UUID,
    text: str,
    speaker_id: str | None = None,
) -> InferenceResult:
    """Generate speech from text using a finetuned model.

    Args:
        db: Database session
        model_id: TTS model ID
        user_id: User ID (for authorization and storage)
        text: Text to synthesize
        speaker_id: Optional speaker ID

    Returns:
        InferenceResult with audio URL or error
    """
    # Get model
    result = await db.execute(
        select(TTSModel).where(
            TTSModel.id == model_id,
            TTSModel.is_deleted == False,  # noqa: E712
        )
    )
    model = result.scalar_one_or_none()

    if not model:
        return InferenceResult(success=False, error="Model not found")

    # Check authorization - must be owner or model must be public
    if model.user_id != user_id and not model.is_public:
        return InferenceResult(success=False, error="Model not accessible")

    # Generate output path
    inference_id = uuid4()
    output_s3_key = f"users/{user_id}/inference/{inference_id}/output.wav"

    # Submit inference job
    job_input = InferenceJobInput(
        model_s3_key=model.model_s3_key,
        text=text,
        output_audio_s3_key=output_s3_key,
        speaker_id=speaker_id,
    )

    # Use sync inference for faster response
    runpod_result = await runpod_service.run_sync_inference(job_input)

    if runpod_result.status != RunPodJobStatus.COMPLETED:
        return InferenceResult(
            success=False,
            error=runpod_result.error or "Inference failed",
        )

    # Update model inference count
    model.inference_count += 1
    await db.commit()

    # Generate presigned URL for output
    try:
        audio_url = s3.generate_presigned_url(output_s3_key, expiration=3600)
    except Exception as e:
        logger.exception("Error generating presigned URL")
        return InferenceResult(
            success=False,
            error=f"Failed to generate audio URL: {str(e)}",
        )

    # Extract duration from output if available
    duration = None
    if runpod_result.output and "duration_seconds" in runpod_result.output:
        duration = runpod_result.output["duration_seconds"]

    return InferenceResult(
        success=True,
        audio_s3_key=output_s3_key,
        audio_url=audio_url,
        duration_seconds=duration,
    )


async def generate_speech_async(
    db: AsyncSession,
    model_id: UUID,
    user_id: UUID,
    text: str,
    speaker_id: str | None = None,
) -> tuple[str, str]:
    """Start async inference and return job ID.

    Use this for longer texts where sync inference might timeout.

    Args:
        db: Database session
        model_id: TTS model ID
        user_id: User ID
        text: Text to synthesize
        speaker_id: Optional speaker ID

    Returns:
        Tuple of (runpod_job_id, output_s3_key)

    Raises:
        ValueError: If model not found or not accessible
    """
    # Get model
    result = await db.execute(
        select(TTSModel).where(
            TTSModel.id == model_id,
            TTSModel.is_deleted == False,  # noqa: E712
        )
    )
    model = result.scalar_one_or_none()

    if not model:
        raise ValueError("Model not found")

    if model.user_id != user_id and not model.is_public:
        raise ValueError("Model not accessible")

    # Generate output path
    inference_id = uuid4()
    output_s3_key = f"users/{user_id}/inference/{inference_id}/output.wav"

    # Submit async inference job
    job_input = InferenceJobInput(
        model_s3_key=model.model_s3_key,
        text=text,
        output_audio_s3_key=output_s3_key,
        speaker_id=speaker_id,
    )

    runpod_result = await runpod_service.submit_inference_job(job_input)

    if runpod_result.error:
        raise ValueError(f"Failed to submit inference job: {runpod_result.error}")

    return runpod_result.job_id, output_s3_key


async def get_inference_status(
    runpod_job_id: str,
    output_s3_key: str,
) -> InferenceResult:
    """Get status of an async inference job.

    Args:
        runpod_job_id: RunPod job ID
        output_s3_key: Expected output S3 key

    Returns:
        InferenceResult with current status
    """
    runpod_result = await runpod_service.get_job_status("inference", runpod_job_id)

    if runpod_result.status == RunPodJobStatus.COMPLETED:
        try:
            audio_url = s3.generate_presigned_url(output_s3_key, expiration=3600)
        except Exception as e:
            logger.exception("Error generating presigned URL")
            return InferenceResult(
                success=False,
                error=f"Failed to generate audio URL: {str(e)}",
            )

        duration = None
        if runpod_result.output and "duration_seconds" in runpod_result.output:
            duration = runpod_result.output["duration_seconds"]

        return InferenceResult(
            success=True,
            audio_s3_key=output_s3_key,
            audio_url=audio_url,
            duration_seconds=duration,
        )

    elif runpod_result.status in [RunPodJobStatus.FAILED, RunPodJobStatus.TIMED_OUT]:
        return InferenceResult(
            success=False,
            error=runpod_result.error or "Inference failed",
        )

    else:
        # Still in progress
        return InferenceResult(
            success=False,
            error=None,  # Not an error, just not done yet
        )
