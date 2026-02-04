# RunPod Serverless Training Endpoint for Qwen3-TTS
FROM runpod/pytorch:2.2.0-py3.10-cuda12.1.1-devel-ubuntu22.04

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy handler code
COPY handler.py .
COPY train_utils.py .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/tmp/huggingface

# RunPod serverless entry point
CMD ["python", "-u", "handler.py"]
