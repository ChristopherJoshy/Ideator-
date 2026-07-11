import logging
import redis.asyncio as redis
from backend.config import settings

logger = logging.getLogger(__name__)

class RedisManager:
    client: redis.Redis = None

redis_manager = RedisManager()

def get_redis_client() -> redis.Redis:
    if redis_manager.client is None:
        logger.info("Connecting to Redis...")
        redis_manager.client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return redis_manager.client

async def close_redis_connection():
    if redis_manager.client is not None:
        logger.info("Closing Redis connection...")
        await redis_manager.client.aclose()
        redis_manager.client = None
