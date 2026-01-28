import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import refresh_token, user  # noqa: F401


async def _create_db(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _drop_db(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(scope="session")
def test_engine():
    settings.jwt_secret_key = settings.jwt_secret_key or "test-secret"
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    asyncio.run(_create_db(engine))
    yield engine
    asyncio.run(_drop_db(engine))
    asyncio.run(engine.dispose())


@pytest.fixture
def async_session_maker(test_engine):
    return async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture
def client(async_session_maker):
    async def override_get_db():
        async with async_session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
