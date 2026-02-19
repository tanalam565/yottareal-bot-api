"""
Redis connection pool service.

Provides lazy-initialized async Redis client access and shared pool lifecycle
helpers for application startup/shutdown flows.
"""

import redis.asyncio as aioredis
import config
import logging

logger = logging.getLogger(__name__)

_redis_pool = None


async def get_redis_client() -> aioredis.Redis:
    """
    Get a Redis client backed by a shared async connection pool.

    Returns:
        aioredis.Redis: Redis client instance.
    """
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.ConnectionPool.from_url(
            config.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=50
        )
        logger.info("Initialized Redis connection pool")
    return aioredis.Redis(connection_pool=_redis_pool)


async def close_redis():
    """Close and reset the shared Redis connection pool."""
    global _redis_pool
    if _redis_pool:
        await _redis_pool.aclose()
        _redis_pool = None
        logger.info("Closed Redis connection pool")