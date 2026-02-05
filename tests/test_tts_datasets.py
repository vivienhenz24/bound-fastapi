import asyncio

from app.api.deps import get_current_active_user
from app.api.routes import tts as tts_routes
from app.main import app
from app.models.tts_dataset import DatasetStatus, TranscriptType, TTSDataset
from app.models.user import User
from app.services import audio_processor, s3


def _run(coro):
    return asyncio.run(coro)


async def _create_user(async_session_maker, email: str) -> User:
    async with async_session_maker() as session:
        user = User(
            email=email,
            hashed_password="hashed",
            first_name="Test",
            last_name="User",
            is_active=True,
            is_verified=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _create_dataset(async_session_maker, user_id):
    async with async_session_maker() as session:
        dataset = TTSDataset(
            user_id=user_id,
            name="Processing dataset",
            description=None,
            audio_s3_key="users/test/datasets/source_audio.wav",
            transcript_s3_key="users/test/datasets/transcript.txt",
            transcript_type=TranscriptType.TEXT.value,
            status=DatasetStatus.PROCESSING.value,
        )
        session.add(dataset)
        await session.commit()
        await session.refresh(dataset)
        return dataset


def _override_current_user(user: User):
    async def _get_user():
        return user

    app.dependency_overrides[get_current_active_user] = _get_user


def test_create_dataset_auto_process_true(client, async_session_maker, monkeypatch):
    user = _run(_create_user(async_session_maker, "datasets@example.com"))
    _override_current_user(user)

    uploaded = []

    def fake_upload(key: str, data: bytes, content_type: str = "application/octet-stream"):
        uploaded.append((key, content_type))

    monkeypatch.setattr(s3, "upload_file", fake_upload)
    monkeypatch.setattr(audio_processor, "validate_audio_file", lambda data: (True, None))
    monkeypatch.setattr(tts_routes, "_process_dataset_task", lambda *args, **kwargs: None)

    response = client.post(
        "/tts/datasets",
        data={
            "name": "Sample dataset",
            "description": "Test upload",
            "transcript_type": "text",
            "auto_process": "true",
        },
        files={
            "audio": ("sample.mp3", b"fake-audio", "audio/mpeg"),
            "transcript": ("transcript.txt", b"hello world", "text/plain"),
        },
    )

    app.dependency_overrides.pop(get_current_active_user, None)

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == DatasetStatus.PROCESSING.value

    audio_upload = next(item for item in uploaded if "source_audio" in item[0])
    transcript_upload = next(item for item in uploaded if "transcript" in item[0])

    assert audio_upload[0].endswith("source_audio.mp3")
    assert audio_upload[1] == "audio/mpeg"
    assert transcript_upload[0].endswith("transcript.txt")
    assert transcript_upload[1] == "text/plain"


def test_create_dataset_invalid_transcript_type(client, async_session_maker, monkeypatch):
    user = _run(_create_user(async_session_maker, "invalid@example.com"))
    _override_current_user(user)

    monkeypatch.setattr(audio_processor, "validate_audio_file", lambda data: (True, None))

    response = client.post(
        "/tts/datasets",
        data={
            "name": "Bad transcript",
            "transcript_type": "bad",
            "auto_process": "true",
        },
        files={
            "audio": ("sample.wav", b"fake-audio", "audio/wav"),
            "transcript": ("transcript.txt", b"hello world", "text/plain"),
        },
    )

    app.dependency_overrides.pop(get_current_active_user, None)

    assert response.status_code == 400
    assert "Invalid transcript_type" in response.json()["detail"]


def test_process_dataset_invalid_status(client, async_session_maker):
    user = _run(_create_user(async_session_maker, "processing@example.com"))
    dataset = _run(_create_dataset(async_session_maker, user.id))
    _override_current_user(user)

    response = client.post(f"/tts/datasets/{dataset.id}/process")

    app.dependency_overrides.pop(get_current_active_user, None)

    assert response.status_code == 400
    assert "Dataset cannot be processed" in response.json()["detail"]
