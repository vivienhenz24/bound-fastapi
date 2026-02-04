"""RunPod Serverless handler for Qwen3-TTS training."""

import json
import logging
import os
import tempfile
from pathlib import Path

import boto3
import runpod
import torch
from safetensors.torch import save_file
from transformers import AutoModelForCausalLM, AutoTokenizer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_s3_client(input_data: dict):
    """Create S3 client from input credentials."""
    return boto3.client(
        "s3",
        aws_access_key_id=input_data["aws_access_key_id"],
        aws_secret_access_key=input_data["aws_secret_access_key"],
        region_name=input_data["aws_region"],
    )


def download_from_s3(s3_client, bucket: str, key: str, local_path: str):
    """Download file from S3."""
    logger.info(f"Downloading s3://{bucket}/{key} to {local_path}")
    s3_client.download_file(bucket, key, local_path)


def upload_to_s3(s3_client, bucket: str, local_path: str, key: str):
    """Upload file to S3."""
    logger.info(f"Uploading {local_path} to s3://{bucket}/{key}")
    s3_client.upload_file(local_path, bucket, key)


def load_training_data(jsonl_path: str) -> list[dict]:
    """Load training data from JSONL file."""
    data = []
    with open(jsonl_path, "r") as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    return data


def train_model(
    base_model: str,
    training_data: list[dict],
    epochs: int,
    learning_rate: float,
    batch_size: int,
    output_dir: str,
    progress_callback=None,
):
    """Train Qwen3-TTS model on provided data.

    This is a simplified training loop. In production, you would use
    the full Qwen3-TTS training scripts with proper audio tokenization.
    """
    logger.info(f"Loading base model: {base_model}")

    # Load model and tokenizer
    # Note: Replace with actual Qwen3-TTS model loading
    tokenizer = AutoTokenizer.from_pretrained(
        base_model,
        trust_remote_code=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
        device_map="auto",
    )

    # Prepare optimizer
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate)

    # Training loop
    model.train()
    total_steps = epochs * (len(training_data) // batch_size + 1)
    current_step = 0
    total_loss = 0.0

    for epoch in range(epochs):
        epoch_loss = 0.0
        num_batches = 0

        for i in range(0, len(training_data), batch_size):
            batch = training_data[i : i + batch_size]

            # Tokenize batch (simplified - actual TTS training needs audio codes)
            texts = [item["text"] for item in batch]
            inputs = tokenizer(
                texts,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=512,
            ).to(model.device)

            # Forward pass
            outputs = model(**inputs, labels=inputs["input_ids"])
            loss = outputs.loss

            # Backward pass
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            epoch_loss += loss.item()
            total_loss += loss.item()
            num_batches += 1
            current_step += 1

            # Report progress
            if progress_callback and current_step % 10 == 0:
                progress_callback(
                    current_epoch=epoch + 1,
                    current_step=current_step,
                    total_steps=total_steps,
                    loss=loss.item(),
                )

        avg_epoch_loss = epoch_loss / max(num_batches, 1)
        logger.info(f"Epoch {epoch + 1}/{epochs}, Loss: {avg_epoch_loss:.4f}")

    # Save model
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Save as safetensors
    model_path = output_path / "model.safetensors"
    save_file(model.state_dict(), str(model_path))

    # Save config
    config_path = output_path / "config.json"
    model.config.save_pretrained(str(output_path))

    # Get model size
    model_size = model_path.stat().st_size

    final_loss = total_loss / max(current_step, 1)

    return {
        "model_path": str(model_path),
        "config_path": str(config_path),
        "model_size_bytes": model_size,
        "final_loss": final_loss,
        "training_samples": len(training_data),
    }


def handler(event):
    """RunPod serverless handler for training jobs."""
    try:
        input_data = event["input"]

        # Extract parameters
        dataset_s3_key = input_data["dataset_s3_key"]
        training_data_s3_key = input_data["training_data_s3_key"]
        output_model_s3_key = input_data["output_model_s3_key"]
        epochs = input_data.get("epochs", 3)
        learning_rate = input_data.get("learning_rate", 1e-5)
        batch_size = input_data.get("batch_size", 4)
        base_model = input_data.get("base_model", "Qwen/Qwen2-0.5B")  # Placeholder
        bucket = input_data["s3_bucket"]

        # Create S3 client
        s3_client = get_s3_client(input_data)

        # Create temp directory for work
        with tempfile.TemporaryDirectory() as tmpdir:
            # Download training data
            training_data_path = os.path.join(tmpdir, "training_data.jsonl")
            download_from_s3(s3_client, bucket, training_data_s3_key, training_data_path)

            # Load training data
            training_data = load_training_data(training_data_path)
            logger.info(f"Loaded {len(training_data)} training samples")

            # Create output directory
            output_dir = os.path.join(tmpdir, "output")

            # Train model
            result = train_model(
                base_model=base_model,
                training_data=training_data,
                epochs=epochs,
                learning_rate=learning_rate,
                batch_size=batch_size,
                output_dir=output_dir,
            )

            # Upload model to S3
            upload_to_s3(s3_client, bucket, result["model_path"], output_model_s3_key)

            # Upload config
            config_s3_key = output_model_s3_key.replace("model.safetensors", "config.json")
            upload_to_s3(s3_client, bucket, result["config_path"], config_s3_key)

            return {
                "status": "success",
                "model_s3_key": output_model_s3_key,
                "model_size_bytes": result["model_size_bytes"],
                "final_loss": result["final_loss"],
                "training_samples": result["training_samples"],
            }

    except Exception as e:
        logger.exception("Training failed")
        return {"status": "error", "error": str(e)}


# Start RunPod serverless
runpod.serverless.start({"handler": handler})
