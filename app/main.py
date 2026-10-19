from fastapi import FastAPI
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

# Mount central API router under both standard versioned path and legacy unversioned path
# This allows all 3 streams to develop independently without modifying main.py
app.include_router(api_router, prefix=settings.API_V1_STR)  # /api/v1/...
app.include_router(api_router, prefix="/api")              # /api/...

@app.get("/health", tags=["health"])
async def root_health():
    return {"status": "ok", "message": "Go to /api/v1/health for detailed status."}
