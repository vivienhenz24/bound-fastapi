"""RunPod Serverless handler for Qwen3-TTS inference."""

import hashlib
import logging
import os
import tempfile
from io import BytesIO
from pathlib import Path

import boto3
import runpod
import soundfile as sf
import torch
from safetensors.torch import load_file
from transformers import AutoModelForCausalLM, AutoTokenizer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Model cache directory
MODEL_CACHE_DIR = Path(os.environ.get("MODEL_CACHE_DIR", "/tmp/tts_models"))
MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Loaded models cache (in-memory)
_loaded_models: dict = {}


def get_s3_client(input_data: dict):
    """Create S3 client from input credentials."""
    return boto3.client(
        "s3",
        aws_access_key_id=input_data["aws_access_key_id"],
        aws_secret_access_key=input_data["aws_secret_access_key"],
        region_name=input_data["aws_region"],
    )


def get_model_cache_key(model_s3_key: str) -> str:
    """Generate cache key for model."""
    return hashlib.md5(model_s3_key.encode()).hexdigest()


def download_model(s3_client, bucket: str, model_s3_key: str) -> Path:
    """Download model from S3 to local cache."""
    cache_key = get_model_cache_key(model_s3_key)
    cache_dir = MODEL_CACHE_DIR / cache_key

    model_path = cache_dir / "model.safetensors"
    config_path = cache_dir / "config.json"

    # Check if already cached
    if model_path.exists() and config_path.exists():
        logger.info(f"Model already cached at {cache_dir}")
        return cache_dir

    # Download model files
    cache_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Downloading model from s3://{bucket}/{model_s3_key}")
    s3_client.download_file(bucket, model_s3_key, str(model_path))

    # Download config
    config_s3_key = model_s3_key.replace("model.safetensors", "config.json")
    try:
        s3_client.download_file(bucket, config_s3_key, str(config_path))
    except Exception as e:
        logger.warning(f"Could not download config: {e}")

    return cache_dir


def load_model(model_dir: Path):
    """Load model from local directory."""
    cache_key = model_dir.name

    # Check if already loaded
    if cache_key in _loaded_models:
        logger.info(f"Using cached model from memory: {cache_key}")
        return _loaded_models[cache_key]

    logger.info(f"Loading model from {model_dir}")

    # Load tokenizer (using base model tokenizer)
    # In production, this would be the Qwen3-TTS tokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        "Qwen/Qwen2-0.5B",  # Placeholder - use actual base model
        trust_remote_code=True,
    )

    # Load model
    model_path = model_dir / "model.safetensors"
    state_dict = load_file(str(model_path))

    model = AutoModelForCausalLM.from_pretrained(
        "Qwen/Qwen2-0.5B",  # Placeholder - use actual base model
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
        device_map="auto",
    )

    # Load finetuned weights
    model.load_state_dict(state_dict, strict=False)
    model.eval()

    # Cache loaded model
    _loaded_models[cache_key] = (model, tokenizer)

    return model, tokenizer


def generate_speech(model, tokenizer, text: str, speaker_id: str = None) -> tuple[bytes, float]:
    """Generate speech from text.

    This is a placeholder - actual implementation depends on Qwen3-TTS API.

    Args:
        model: Loaded TTS model
        tokenizer: TTS tokenizer
        text: Text to synthesize
        speaker_id: Optional speaker ID

    Returns:
        Tuple of (audio_bytes, duration_seconds)
    """
    logger.info(f"Generating speech for: {text[:50]}...")

    # Placeholder implementation
    # In production, this would use the actual Qwen3-TTS generation API

    # For now, generate silence as placeholder
    sample_rate = 24000
    duration = len(text) * 0.05  # Rough estimate
    num_samples = int(sample_rate * duration)

    # Generate placeholder audio (silence with slight noise)
    audio = torch.randn(num_samples) * 0.001
    audio = audio.numpy()

    # Convert to WAV bytes
    buffer = BytesIO()
    sf.write(buffer, audio, sample_rate, format="WAV")
    buffer.seek(0)

    return buffer.read(), duration


def handler(event):
    """RunPod serverless handler for inference jobs."""
    try:
        input_data = event["input"]

        # Extract parameters
        model_s3_key = input_data["model_s3_key"]
        text = input_data["text"]
        output_audio_s3_key = input_data["output_audio_s3_key"]
        speaker_id = input_data.get("speaker_id")
        bucket = input_data["s3_bucket"]

        # Create S3 client
        s3_client = get_s3_client(input_data)

        # Download model (uses cache if available)
        model_dir = download_model(s3_client, bucket, model_s3_key)

        # Load model
        model, tokenizer = load_model(model_dir)

        # Generate speech
        audio_bytes, duration = generate_speech(model, tokenizer, text, speaker_id)

        # Upload audio to S3
        logger.info(f"Uploading audio to s3://{bucket}/{output_audio_s3_key}")
        s3_client.put_object(
            Bucket=bucket,
            Key=output_audio_s3_key,
            Body=audio_bytes,
            ContentType="audio/wav",
        )

        return {
            "status": "success",
            "audio_s3_key": output_audio_s3_key,
            "duration_seconds": duration,
        }

    except Exception as e:
        logger.exception("Inference failed")
        return {"status": "error", "error": str(e)}


# Start RunPod serverless
runpod.serverless.start({"handler": handler})
