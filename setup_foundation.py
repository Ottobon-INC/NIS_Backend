import os

files = {
    "requirements.txt": """fastapi==0.111.0
uvicorn==0.30.1
pydantic==2.7.4
pydantic-settings==2.3.4
SQLAlchemy==2.0.30
alembic==1.13.1
asyncpg==0.29.0
psycopg2-binary==2.9.9
redis==5.0.6
httpx==0.27.0
pytest==8.2.2
pytest-asyncio==0.23.7
""",
    ".env.example": """PROJECT_NAME="NetworkOS API"
API_V1_STR="/api/v1"
ENVIRONMENT="development"

# PostgreSQL
POSTGRES_SERVER="localhost"
POSTGRES_USER="postgres"
POSTGRES_PASSWORD="postgres"
POSTGRES_DB="networkos"
POSTGRES_PORT="5432"

# Redis
REDIS_HOST="localhost"
REDIS_PORT="6379"
""",
    "app/__init__.py": "",
    "app/api/__init__.py": "",
    "app/api/dependencies.py": "",
    "app/api/v1/__init__.py": "",
    "app/api/v1/endpoints/__init__.py": "",
    "app/core/__init__.py": "",
    "app/db/__init__.py": "",
    "app/models/__init__.py": "",
    "app/schemas/__init__.py": "",
    "app/services/__init__.py": "",
    "app/repositories/__init__.py": "",
    "app/workers/__init__.py": "",
    "tests/__init__.py": "",
    "tests/api/__init__.py": "",
    "migrations/__init__.py": "",

    "app/core/config.py": """import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import computed_field

class Settings(BaseSettings):
    PROJECT_NAME: str = "NetworkOS API"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"

    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "networkos"
    POSTGRES_PORT: int = 5432

    @computed_field
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    
    @computed_field
    @property
    def SQLALCHEMY_SYNC_DATABASE_URI(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    
    @computed_field
    @property
    def REDIS_URI(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True, extra="ignore")

settings = Settings()
""",
    "app/core/exceptions.py": """from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
import logging

logger = logging.getLogger("networkos")

async def custom_validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid request parameters",
                "details": exc.errors()
            }
        },
    )

async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    logger.error(f"Database error: {str(exc)}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error": {
                "code": "DATABASE_ERROR",
                "message": "An internal database error occurred."
            }
        },
    )

async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred."
            }
        },
    )
""",
    "app/core/logging.py": """import logging
import sys

def setup_logging():
    logger = logging.getLogger("networkos")
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    
    if not logger.handlers:
        logger.addHandler(handler)
        
    return logger
""",
    "app/db/session.py": """from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings

engine = create_async_engine(
    settings.SQLALCHEMY_DATABASE_URI,
    echo=settings.ENVIRONMENT == "development",
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            raise e
        finally:
            await session.close()
""",
    "app/db/base.py": """from sqlalchemy.orm import declarative_base

Base = declarative_base()
""",
    "app/db/redis.py": """from redis.asyncio import Redis
from app.core.config import settings

redis_client = Redis.from_url(
    settings.REDIS_URI, 
    encoding="utf-8", 
    decode_responses=True
)

async def get_redis():
    return redis_client
""",
    "app/schemas/health.py": """from pydantic import BaseModel

class HealthResponse(BaseModel):
    status: str
    database: str
    redis: str
""",
    "app/api/v1/endpoints/health.py": """from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from redis.asyncio import Redis
import logging

from app.db.session import get_db
from app.db.redis import get_redis
from app.schemas.health import HealthResponse

router = APIRouter()
logger = logging.getLogger("networkos")

@router.get("/", response_model=HealthResponse, status_code=status.HTTP_200_OK)
async def health_check(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis)
):
    db_status = "disconnected"
    redis_status = "disconnected"
    app_status = "ok"

    try:
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        app_status = "degraded"

    try:
        await redis.ping()
        redis_status = "connected"
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        app_status = "degraded"

    return HealthResponse(
        status=app_status,
        database=db_status,
        redis=redis_status
    )
""",
    "app/api/v1/api.py": """from fastapi import APIRouter
from app.api.v1.endpoints import health

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
""",
    "app/main.py": """from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.exceptions import (
    custom_validation_exception_handler,
    sqlalchemy_exception_handler,
    global_exception_handler
)
from app.api.v1.api import api_router

# Setup structured logging
setup_logging()

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    description="NetworkOS Backend API Foundation"
)

# CORS Config
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Exception Handlers
app.add_exception_handler(RequestValidationError, custom_validation_exception_handler)
app.add_exception_handler(SQLAlchemyError, sqlalchemy_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# Routers
app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/health", tags=["health"])
async def root_health():
    return {"status": "ok", "message": "Go to /api/v1/health for detailed status."}
""",
    "Dockerfile": """FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
""",
    "docker-compose.yml": """version: '3.8'

services:
  api:
    build: .
    ports:
      - "8080:8080"
    volumes:
      - .:/app
    environment:
      - ENVIRONMENT=development
      - POSTGRES_SERVER=db
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=postgres
      - POSTGRES_DB=networkos
      - REDIS_HOST=redis
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy

  db:
    image: postgres:15-alpine
    ports:
      - "5432:5432"
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=postgres
      - POSTGRES_DB=networkos
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
""",
    "alembic.ini": """[alembic]
script_location = migrations
prepend_sys_path = .
version_path_separator = os

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
""",
    "migrations/env.py": """import asyncio
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

from app.core.config import settings
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def get_url():
    return settings.SQLALCHEMY_DATABASE_URI

def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
""",
    "migrations/script.py.mako": '"""${message}\n\nRevision ID: ${up_revision}\nRevises: ${down_revision | comma,n}\nCreate Date: ${create_date}\n\n"""\nfrom typing import Sequence, Union\nfrom alembic import op\nimport sqlalchemy as sa\n${imports if imports else ""}\n\n# revision identifiers, used by Alembic.\nrevision: str = ${repr(up_revision)}\ndown_revision: Union[str, None] = ${repr(down_revision)}\nbranch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}\ndepends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}\n\n\ndef upgrade() -> None:\n    ${upgrades if upgrades else "pass"}\n\n\ndef downgrade() -> None:\n    ${downgrades if downgrades else "pass"}\n',
    "tests/conftest.py": """import pytest
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

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session", autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with TestingSessionLocal() as session:
        yield session

@pytest.fixture
async def redis_client() -> AsyncGenerator[Redis, None]:
    redis = Redis.from_url(settings.REDIS_URI, encoding="utf-8", decode_responses=True)
    yield redis
    await redis.aclose()

@pytest.fixture
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
""",
    "tests/api/test_health.py": """import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_root_health(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "message": "Go to /api/v1/health for detailed status."}

@pytest.mark.asyncio
async def test_api_v1_health(client: AsyncClient):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
""",
    "tests/pytest.ini": """[pytest]
asyncio_mode = auto
filterwarnings =
    ignore::DeprecationWarning
""",
    "README.md": """# NetworkOS Backend

## 1. What NetworkOS is
NetworkOS is a relationship intelligence and network opportunity platform. It ingests LinkedIn profiles, enriches contacts, maps relationships, integrates founder meeting notes, tracks opportunities, and drafts intelligent introductions.

## 2. Current Backend Architecture
This repository contains the foundation for the NetworkOS backend. It is designed to be highly modular and production-ready, featuring:
- **FastAPI** for high-performance API delivery.
- **SQLAlchemy 2.x (Async)** for asynchronous database operations.
- **Redis** for future background task queues and caching.
- **Dependency Injection** for database and Redis sessions.
- **Centralized Error Handling** to return consistent JSON responses.
- **API Versioning** (`/api/v1/...`).

## 3. Technology Stack
- **Python:** 3.12+
- **API Framework:** FastAPI
- **Database:** PostgreSQL 15
- **ORM:** SQLAlchemy 2.x
- **Migrations:** Alembic
- **Caching / Tasks:** Redis
- **Validation:** Pydantic v2
- **Testing:** pytest
- **Containerization:** Docker & Docker Compose

## 4. Project Structure
```
backend/
├── app/
│   ├── api/          # API Routers and versioning
│   ├── core/         # Configuration, logging, exception handling
│   ├── db/           # Database setup, sessions, Redis client
│   ├── models/       # SQLAlchemy models
│   ├── schemas/      # Pydantic validation schemas
│   ├── services/     # Business logic layer
│   ├── repositories/ # Database interaction layer
│   └── main.py       # FastAPI application entrypoint
├── migrations/       # Alembic migrations
├── tests/            # pytest suite
├── requirements.txt  # Python dependencies
├── .env.example      # Example environment variables
├── Dockerfile        # Backend container definition
└── docker-compose.yml# Multi-container orchestration
```

## 5. Environment Setup
1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: .\\venv\\Scripts\\Activate.ps1
   pip install -r requirements.txt
   ```

## 6. How to start using Docker
The easiest way to run the entire stack (FastAPI, PostgreSQL, Redis) is using Docker Compose:

```bash
docker compose up --build
```
This will start the backend at `http://localhost:8080`.

## 7. How to run tests
Make sure your virtual environment is activated, and your database/Redis containers are running (since the tests verify connectivity).
Then run:
```bash
pytest
```

## 8. How to access API documentation
Once the server is running, navigate to:
- Swagger UI: [http://localhost:8080/docs](http://localhost:8080/docs)
- ReDoc: [http://localhost:8080/redoc](http://localhost:8080/redoc)

## 9. Current Scope
- Modular structure implementation.
- API Versioning, Logging, and Error Handling.
- Postgres and Redis asynchronous connectivity.
- Health endpoints (`/health` and `/api/v1/health`).
- Alembic migration environment setup.

## 10. What is intentionally NOT implemented yet
- **Business Logic:** No features like contacts, opportunities, or meeting intelligence are implemented yet.
- **Database Tables:** Only the infrastructure is set up. We haven't created the tables for NetworkOS models yet.
- **AI/LLM Logic:** No LangChain or fake AI endpoints.
- **Worker Queues:** Redis is connected, but Celery/Arq background workers are not configured yet.
"""
}

# Delete the old main.py if it exists to avoid confusion
if os.path.exists("main.py"):
    os.remove("main.py")

for filepath, content in files.items():
    directory = os.path.dirname(filepath)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

print("Foundation structure generated successfully.")
