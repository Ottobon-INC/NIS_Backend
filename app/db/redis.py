from redis.asyncio import Redis
from app.core.config import settings

redis_client = Redis.from_url(
    settings.REDIS_URI, 
    encoding="utf-8", 
    decode_responses=True
)

async def get_redis():
    return redis_client
