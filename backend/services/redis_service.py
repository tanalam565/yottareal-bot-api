# backend/services/redis_service.py

import redis.asyncio as aioredis
import config
import logging

logger = logging.getLogger(__name__)

_redis_pool = None


async def get_redis_client() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.ConnectionPool.from_url(
            config.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=50
        )
    return aioredis.Redis(connection_pool=_redis_pool)


async def close_redis():
    global _redis_pool
    if _redis_pool:
        await _redis_pool.aclose()
        _redis_pool = None