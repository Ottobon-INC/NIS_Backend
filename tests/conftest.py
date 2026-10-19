import pytest
import pytest_asyncio
import asyncio
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from redis.asyncio import Redis

from app.main import app
from app.db.session import get_db
from app.db.base import Base
from app.core.config import settings
from app.db.redis import get_redis

TEST_DB_URL = settings.SQLALCHEMY_DATABASE_URI
engine = create_async_engine(TEST_DB_URL, future=True, echo=False)
TestingSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with TestingSessionLocal() as session:
        yield session

@pytest_asyncio.fixture
async def redis_client() -> AsyncGenerator[Redis, None]:
    redis = Redis.from_url(settings.REDIS_URI, encoding="utf-8", decode_responses=True)
    yield redis
    await redis.aclose()

@pytest_asyncio.fixture
async def client(db_session, redis_client) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield db_session
        
    async def override_get_redis():
        yield redis_client

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = override_get_redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
        
    app.dependency_overrides.clear()
