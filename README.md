# NetworkOS Backend

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
   source venv/bin/activate  # On Windows: .\venv\Scripts\Activate.ps1
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
