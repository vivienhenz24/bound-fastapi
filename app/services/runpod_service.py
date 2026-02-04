"""RunPod Serverless API client for TTS training and inference.

Handles:
- Submitting training jobs to RunPod
- Polling job status
- Cancelling jobs
- Submitting inference requests
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RUNPOD_API_BASE = "https://api.runpod.ai/v2"


class RunPodJobStatus(str, Enum):
    """RunPod job status values."""

    IN_QUEUE = "IN_QUEUE"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


@dataclass
class RunPodJobResult:
    """Result from a RunPod job."""

    job_id: str
    status: RunPodJobStatus
    output: dict[str, Any] | None = None
    error: str | None = None
    execution_time: float | None = None


@dataclass
class TrainingJobInput:
    """Input parameters for a training job."""

    dataset_s3_key: str
    training_data_s3_key: str
    output_model_s3_key: str
    epochs: int
    learning_rate: float
    batch_size: int
    base_model: str = "Qwen3-TTS-12Hz-1.7B-Base"
    # AWS credentials for S3 access
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region: str | None = None
    s3_bucket: str | None = None


@dataclass
class InferenceJobInput:
    """Input parameters for an inference job."""

    model_s3_key: str
    text: str
    output_audio_s3_key: str
    speaker_id: str | None = None
    # AWS credentials for S3 access
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region: str | None = None
    s3_bucket: str | None = None


def _get_headers() -> dict[str, str]:
    """Get headers for RunPod API requests."""
    return {
        "Authorization": f"Bearer {settings.runpod_api_key}",
        "Content-Type": "application/json",
    }


def _add_aws_credentials(input_data: dict) -> dict:
    """Add AWS credentials to input data for S3 access from RunPod."""
    input_data["aws_access_key_id"] = settings.aws_access_key_id
    input_data["aws_secret_access_key"] = settings.aws_secret_access_key
    input_data["aws_region"] = settings.aws_region
    input_data["s3_bucket"] = settings.s3_bucket_name
    return input_data


async def submit_training_job(job_input: TrainingJobInput) -> RunPodJobResult:
    """Submit a training job to RunPod Serverless.

    Args:
        job_input: Training job parameters

    Returns:
        RunPodJobResult with job_id and initial status
    """
    endpoint_id = settings.runpod_training_endpoint_id
    url = f"{RUNPOD_API_BASE}/{endpoint_id}/run"

    input_data = {
        "dataset_s3_key": job_input.dataset_s3_key,
        "training_data_s3_key": job_input.training_data_s3_key,
        "output_model_s3_key": job_input.output_model_s3_key,
        "epochs": job_input.epochs,
        "learning_rate": job_input.learning_rate,
        "batch_size": job_input.batch_size,
        "base_model": job_input.base_model,
    }
    input_data = _add_aws_credentials(input_data)

    payload = {"input": input_data}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=_get_headers(), json=payload)
            response.raise_for_status()
            data = response.json()

            return RunPodJobResult(
                job_id=data["id"],
                status=RunPodJobStatus.IN_QUEUE,
            )

    except httpx.HTTPStatusError as e:
        logger.error(f"RunPod API error: {e.response.status_code} - {e.response.text}")
        return RunPodJobResult(
            job_id="",
            status=RunPodJobStatus.FAILED,
            error=f"RunPod API error: {e.response.status_code}",
        )
    except Exception as e:
        logger.exception("Error submitting training job to RunPod")
        return RunPodJobResult(
            job_id="",
            status=RunPodJobStatus.FAILED,
            error=str(e),
        )


async def submit_inference_job(job_input: InferenceJobInput) -> RunPodJobResult:
    """Submit an inference job to RunPod Serverless.

    Args:
        job_input: Inference job parameters

    Returns:
        RunPodJobResult with job_id and initial status
    """
    endpoint_id = settings.runpod_inference_endpoint_id
    url = f"{RUNPOD_API_BASE}/{endpoint_id}/run"

    input_data = {
        "model_s3_key": job_input.model_s3_key,
        "text": job_input.text,
        "output_audio_s3_key": job_input.output_audio_s3_key,
    }
    if job_input.speaker_id:
        input_data["speaker_id"] = job_input.speaker_id
    input_data = _add_aws_credentials(input_data)

    payload = {"input": input_data}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=_get_headers(), json=payload)
            response.raise_for_status()
            data = response.json()

            return RunPodJobResult(
                job_id=data["id"],
                status=RunPodJobStatus.IN_QUEUE,
            )

    except httpx.HTTPStatusError as e:
        logger.error(f"RunPod API error: {e.response.status_code} - {e.response.text}")
        return RunPodJobResult(
            job_id="",
            status=RunPodJobStatus.FAILED,
            error=f"RunPod API error: {e.response.status_code}",
        )
    except Exception as e:
        logger.exception("Error submitting inference job to RunPod")
        return RunPodJobResult(
            job_id="",
            status=RunPodJobStatus.FAILED,
            error=str(e),
        )


async def get_job_status(endpoint_type: str, job_id: str) -> RunPodJobResult:
    """Get the status of a RunPod job.

    Args:
        endpoint_type: 'training' or 'inference'
        job_id: RunPod job ID

    Returns:
        RunPodJobResult with current status and output if completed
    """
    if endpoint_type == "training":
        endpoint_id = settings.runpod_training_endpoint_id
    else:
        endpoint_id = settings.runpod_inference_endpoint_id

    url = f"{RUNPOD_API_BASE}/{endpoint_id}/status/{job_id}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=_get_headers())
            response.raise_for_status()
            data = response.json()

            status = RunPodJobStatus(data["status"])
            output = data.get("output")
            error = None
            execution_time = data.get("executionTime")

            # Check for error in output
            if status == RunPodJobStatus.FAILED:
                error = data.get("error") or (output.get("error") if output else None)

            return RunPodJobResult(
                job_id=job_id,
                status=status,
                output=output,
                error=error,
                execution_time=execution_time,
            )

    except httpx.HTTPStatusError as e:
        logger.error(f"RunPod status error: {e.response.status_code} - {e.response.text}")
        return RunPodJobResult(
            job_id=job_id,
            status=RunPodJobStatus.FAILED,
            error=f"Failed to get status: {e.response.status_code}",
        )
    except Exception as e:
        logger.exception(f"Error getting job status: {job_id}")
        return RunPodJobResult(
            job_id=job_id,
            status=RunPodJobStatus.FAILED,
            error=str(e),
        )


async def cancel_job(endpoint_type: str, job_id: str) -> bool:
    """Cancel a running RunPod job.

    Args:
        endpoint_type: 'training' or 'inference'
        job_id: RunPod job ID

    Returns:
        True if cancellation was successful
    """
    if endpoint_type == "training":
        endpoint_id = settings.runpod_training_endpoint_id
    else:
        endpoint_id = settings.runpod_inference_endpoint_id

    url = f"{RUNPOD_API_BASE}/{endpoint_id}/cancel/{job_id}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=_get_headers())
            response.raise_for_status()
            return True

    except httpx.HTTPStatusError as e:
        logger.error(f"RunPod cancel error: {e.response.status_code} - {e.response.text}")
        return False
    except Exception as e:
        logger.exception(f"Error cancelling job: {job_id}")
        return False


async def run_sync_inference(job_input: InferenceJobInput, timeout: float = 120.0) -> RunPodJobResult:
    """Run inference synchronously (wait for completion).

    This is useful for quick inference requests where we want to wait
    for the result rather than polling.

    Args:
        job_input: Inference job parameters
        timeout: Maximum time to wait in seconds

    Returns:
        RunPodJobResult with output or error
    """
    endpoint_id = settings.runpod_inference_endpoint_id
    url = f"{RUNPOD_API_BASE}/{endpoint_id}/runsync"

    input_data = {
        "model_s3_key": job_input.model_s3_key,
        "text": job_input.text,
        "output_audio_s3_key": job_input.output_audio_s3_key,
    }
    if job_input.speaker_id:
        input_data["speaker_id"] = job_input.speaker_id
    input_data = _add_aws_credentials(input_data)

    payload = {"input": input_data}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=_get_headers(), json=payload)
            response.raise_for_status()
            data = response.json()

            status = RunPodJobStatus(data["status"])
            output = data.get("output")
            error = data.get("error")

            if status == RunPodJobStatus.FAILED:
                error = error or (output.get("error") if output else "Unknown error")

            return RunPodJobResult(
                job_id=data.get("id", ""),
                status=status,
                output=output,
                error=error,
                execution_time=data.get("executionTime"),
            )

    except httpx.TimeoutException:
        logger.error(f"Inference timeout after {timeout}s")
        return RunPodJobResult(
            job_id="",
            status=RunPodJobStatus.TIMED_OUT,
            error=f"Request timed out after {timeout}s",
        )
    except httpx.HTTPStatusError as e:
        logger.error(f"RunPod sync error: {e.response.status_code} - {e.response.text}")
        return RunPodJobResult(
            job_id="",
            status=RunPodJobStatus.FAILED,
            error=f"RunPod API error: {e.response.status_code}",
        )
    except Exception as e:
        logger.exception("Error running sync inference")
        return RunPodJobResult(
            job_id="",
            status=RunPodJobStatus.FAILED,
            error=str(e),
        )
