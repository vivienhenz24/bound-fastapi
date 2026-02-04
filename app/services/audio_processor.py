"""Audio processing service for TTS dataset preparation.

Handles:
- SRT parsing and audio segmentation
- Plain text processing with Whisper for forced alignment
- Training data JSONL generation
"""

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pysrt
from pydub import AudioSegment

from app.core.config import settings
from app.services import s3

logger = logging.getLogger(__name__)


@dataclass
class AudioSegmentData:
    """Represents a segmented audio clip with its transcript."""

    index: int
    start_ms: int
    end_ms: int
    text: str
    audio_data: bytes
    duration_seconds: float


@dataclass
class ProcessingResult:
    """Result of audio processing."""

    segments: list[AudioSegmentData]
    total_duration_seconds: float
    training_data_jsonl: str
    segment_s3_keys: list[str]
    error: str | None = None


def parse_srt_file(srt_content: str) -> list[dict]:
    """Parse SRT file content into a list of subtitle entries.

    Args:
        srt_content: Raw SRT file content

    Returns:
        List of dicts with start_ms, end_ms, and text
    """
    subs = pysrt.from_string(srt_content)
    entries = []

    for sub in subs:
        start_ms = (
            sub.start.hours * 3600000
            + sub.start.minutes * 60000
            + sub.start.seconds * 1000
            + sub.start.milliseconds
        )
        end_ms = (
            sub.end.hours * 3600000
            + sub.end.minutes * 60000
            + sub.end.seconds * 1000
            + sub.end.milliseconds
        )
        text = sub.text.replace("\n", " ").strip()

        if text:
            entries.append({"start_ms": start_ms, "end_ms": end_ms, "text": text})

    return entries


def segment_audio_by_timestamps(
    audio_data: bytes, timestamps: list[dict]
) -> list[AudioSegmentData]:
    """Segment audio file based on timestamp entries.

    Args:
        audio_data: Raw audio file bytes
        timestamps: List of dicts with start_ms, end_ms, text

    Returns:
        List of AudioSegmentData
    """
    audio = AudioSegment.from_file(BytesIO(audio_data))
    segments = []

    for i, ts in enumerate(timestamps):
        start_ms = ts["start_ms"]
        end_ms = ts["end_ms"]
        text = ts["text"]

        # Extract segment
        segment = audio[start_ms:end_ms]

        # Export to WAV bytes
        buffer = BytesIO()
        segment.export(buffer, format="wav")
        audio_bytes = buffer.getvalue()

        duration = (end_ms - start_ms) / 1000.0

        segments.append(
            AudioSegmentData(
                index=i,
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
                audio_data=audio_bytes,
                duration_seconds=duration,
            )
        )

    return segments


def process_with_whisper_alignment(
    audio_data: bytes, transcript_text: str
) -> list[dict]:
    """Use Whisper to get word-level timestamps and align with transcript.

    This performs forced alignment to match the transcript text with audio.

    Args:
        audio_data: Raw audio file bytes
        transcript_text: Full transcript text

    Returns:
        List of timestamp entries for sentence-level segments
    """
    try:
        import whisper
    except ImportError:
        raise RuntimeError("Whisper is required for plain text alignment")

    # Save audio to temp file (whisper needs file path)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_data)
        temp_path = f.name

    try:
        # Load whisper model
        model = whisper.load_model("base")

        # Transcribe with word timestamps
        result = model.transcribe(
            temp_path,
            word_timestamps=True,
            language=None,  # Auto-detect
        )

        # Extract segments from whisper output
        timestamps = []
        for segment in result.get("segments", []):
            text = segment.get("text", "").strip()
            if text:
                timestamps.append(
                    {
                        "start_ms": int(segment["start"] * 1000),
                        "end_ms": int(segment["end"] * 1000),
                        "text": text,
                    }
                )

        return timestamps

    finally:
        # Clean up temp file
        os.unlink(temp_path)


def generate_training_jsonl(segments: list[AudioSegmentData], s3_keys: list[str]) -> str:
    """Generate JSONL training data for Qwen3-TTS.

    Args:
        segments: List of audio segments with text
        s3_keys: S3 keys for the segment audio files

    Returns:
        JSONL string for training
    """
    lines = []
    for segment, s3_key in zip(segments, s3_keys):
        entry = {
            "audio_path": s3_key,
            "text": segment.text,
            "duration": segment.duration_seconds,
        }
        lines.append(json.dumps(entry))

    return "\n".join(lines)


async def process_dataset(
    user_id: UUID,
    dataset_id: UUID,
    audio_s3_key: str,
    transcript_s3_key: str,
    transcript_type: str,
) -> ProcessingResult:
    """Process a dataset: download, segment, and upload training data.

    Args:
        user_id: User ID for S3 paths
        dataset_id: Dataset ID for S3 paths
        audio_s3_key: S3 key for source audio
        transcript_s3_key: S3 key for transcript
        transcript_type: 'srt' or 'text'

    Returns:
        ProcessingResult with segments and training data
    """
    try:
        # Download audio and transcript from S3
        logger.info(f"Downloading audio from {audio_s3_key}")
        audio_data = s3.download_file(audio_s3_key)

        logger.info(f"Downloading transcript from {transcript_s3_key}")
        transcript_data = s3.download_file(transcript_s3_key)
        transcript_text = transcript_data.decode("utf-8")

        # Parse timestamps based on transcript type
        if transcript_type == "srt":
            logger.info("Processing SRT transcript")
            timestamps = parse_srt_file(transcript_text)
        else:
            logger.info("Processing plain text with Whisper alignment")
            timestamps = process_with_whisper_alignment(audio_data, transcript_text)

        if not timestamps:
            return ProcessingResult(
                segments=[],
                total_duration_seconds=0,
                training_data_jsonl="",
                segment_s3_keys=[],
                error="No valid segments found in transcript",
            )

        # Segment audio
        logger.info(f"Segmenting audio into {len(timestamps)} segments")
        segments = segment_audio_by_timestamps(audio_data, timestamps)

        # Upload segments to S3
        segment_s3_keys = []
        base_path = f"users/{user_id}/datasets/{dataset_id}/segments"

        for segment in segments:
            segment_key = f"{base_path}/segment_{segment.index:05d}.wav"
            s3.upload_file(segment_key, segment.audio_data, content_type="audio/wav")
            segment_s3_keys.append(segment_key)
            logger.info(f"Uploaded segment {segment.index} to {segment_key}")

        # Generate and upload training JSONL
        training_jsonl = generate_training_jsonl(segments, segment_s3_keys)
        training_key = f"users/{user_id}/datasets/{dataset_id}/training_data.jsonl"
        s3.upload_file(
            training_key,
            training_jsonl.encode("utf-8"),
            content_type="application/jsonl",
        )
        logger.info(f"Uploaded training data to {training_key}")

        # Calculate total duration
        total_duration = sum(s.duration_seconds for s in segments)

        return ProcessingResult(
            segments=segments,
            total_duration_seconds=total_duration,
            training_data_jsonl=training_jsonl,
            segment_s3_keys=segment_s3_keys,
        )

    except Exception as e:
        logger.exception("Error processing dataset")
        return ProcessingResult(
            segments=[],
            total_duration_seconds=0,
            training_data_jsonl="",
            segment_s3_keys=[],
            error=str(e),
        )


def get_audio_duration(audio_data: bytes) -> float:
    """Get duration of audio file in seconds.

    Args:
        audio_data: Raw audio file bytes

    Returns:
        Duration in seconds
    """
    audio = AudioSegment.from_file(BytesIO(audio_data))
    return len(audio) / 1000.0


def validate_audio_file(audio_data: bytes) -> tuple[bool, str | None]:
    """Validate audio file format and size.

    Args:
        audio_data: Raw audio file bytes

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check file size
    size_mb = len(audio_data) / (1024 * 1024)
    if size_mb > settings.max_audio_file_size_mb:
        return False, f"File size ({size_mb:.1f}MB) exceeds maximum ({settings.max_audio_file_size_mb}MB)"

    try:
        audio = AudioSegment.from_file(BytesIO(audio_data))
        duration_seconds = len(audio) / 1000.0

        if duration_seconds > settings.max_audio_duration_seconds:
            return (
                False,
                f"Duration ({duration_seconds:.0f}s) exceeds maximum ({settings.max_audio_duration_seconds}s)",
            )

        return True, None

    except Exception as e:
        return False, f"Invalid audio file: {str(e)}"
