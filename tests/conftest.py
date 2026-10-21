import pytest
import asyncio
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool
from redis.asyncio import Redis

from app.main import app
from app.db.session import get_db
from app.db.base import Base
from app.core.config import settings
from app.db.redis import get_redis

TEST_DB_URL = settings.SQLALCHEMY_DATABASE_URI
engine = create_async_engine(TEST_DB_URL, future=True, echo=False, poolclass=NullPool)
TestingSessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with TestingSessionLocal() as session:
        yield session
        await session.rollback()

@pytest.fixture
async def redis_client() -> AsyncGenerator[Redis, None]:
    redis = Redis.from_url(settings.REDIS_URI, encoding="utf-8", decode_responses=True)
    yield redis
    await redis.aclose()

@pytest.fixture
async def client(redis_client) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        async with TestingSessionLocal() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
        
    async def override_get_redis():
        yield redis_client

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = override_get_redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as ac:
        yield ac
        
    app.dependency_overrides.clear()
