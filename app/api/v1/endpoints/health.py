from fastapi import APIRouter, Depends, status
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
