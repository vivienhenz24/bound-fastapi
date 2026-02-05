# CLAUDE.md

## Project Overview

FastAPI backend for TTS (Text-to-Speech) data preparation. Users can upload audio files with transcripts (SRT or plain text), which are then segmented and prepared for TTS model training.

## Recent Changes (2026-02-04)

### TTS Data Preparation Feature

Added functionality for users to upload and process audio datasets:

**Database:**
- `app/models/tts_dataset.py` - TTSDataset model (status: pending/processing/ready/failed)
- `migrations/versions/b2c3d4e5f6a7_add_tts_tables.py` - Migration for tts_datasets table

**API Endpoints:**
- `POST /tts/datasets` - Upload audio + transcript (multipart form)
- `GET /tts/datasets` - List user's datasets
- `GET /tts/datasets/{id}` - Get dataset details
- `DELETE /tts/datasets/{id}` - Delete dataset
- `POST /tts/datasets/{id}/process` - Trigger audio segmentation

**Services:**
- `app/services/audio_processor.py` - SRT parsing, audio segmentation with pydub
- `app/services/s3.py` - S3 upload/download with session token support

**Schemas:**
- `app/schemas/tts.py` - Pydantic models for dataset CRUD

## Commands

```bash
# Install dependencies
uv sync

# Run migrations
uv run alembic upgrade head

# Start dev server
uv run uvicorn app.main:app --reload

# Start database (Docker)
docker compose up -d db
```

## Environment Variables (.env.local)

```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/bound
JWT_SECRET_KEY=<generate with: openssl rand -hex 32>
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_SESSION_TOKEN=  # if using temporary credentials
AWS_REGION=
S3_BUCKET_NAME=
```

## S3 Storage Structure

```
{bucket}/users/{user_id}/datasets/{dataset_id}/
├── source_audio.wav
├── transcript.{txt|srt}
├── segments/
│   ├── segment_00000.wav
│   ├── segment_00001.wav
│   └── ...
└── training_data.jsonl
```

## Architecture Notes

- Audio processing runs as background tasks (FastAPI BackgroundTasks)
- SRT files provide timestamps for segmentation
- Plain text creates single segment (full audio)
- All files stored in S3, metadata in PostgreSQL
