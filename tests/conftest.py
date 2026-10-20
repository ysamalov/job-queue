import os
from typing import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text, event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/jobqueue_test",
)

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["WORKER_TOKEN"] = "test-token"
os.environ["TESTING"] = "1"

# Patch database module to use test engine BEFORE importing the app
import app.database as db_mod  # noqa: E402
from app.models import Base  # noqa: E402

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
TestSessionFactory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

# Replace the engine and session factory used by the app
db_mod.engine = test_engine
db_mod.async_session_factory = TestSessionFactory


async def _test_get_session() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionFactory() as session:
        yield session


db_mod.get_session = _test_get_session

from app.main import app  # noqa: E402
from app.database import get_session  # noqa: E402

app.dependency_overrides[get_session] = _test_get_session

WORKER_HEADERS = {
    "Authorization": "Bearer test-token",
    "X-Worker-Id": "test-worker",
}

_tables_created = False


@pytest_asyncio.fixture(autouse=True)
async def _setup_and_clean():
    global _tables_created
    if not _tables_created:
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        _tables_created = True
    yield
    async with TestSessionFactory() as session:
        await session.execute(text("DELETE FROM jobs"))
        await session.commit()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
