"""
Redis client for pub/sub messaging (SSE streaming).

Uses ElastiCache Serverless in production.
"""

import json
import logging
from typing import AsyncIterator, Optional

import redis.asyncio as redis
from redis.asyncio.client import PubSub

from app.core.config import settings

logger = logging.getLogger(__name__)

# Global Redis client instance
_redis_client: Optional[redis.Redis] = None


async def get_redis() -> redis.Redis:
    """
    Get or create async Redis client.

    Returns:
        Async Redis client instance

    Raises:
        RuntimeError: If REDIS_URL is not configured
    """
    global _redis_client

    if _redis_client is None:
        if not settings.REDIS_URL:
            raise RuntimeError(
                "REDIS_URL is not configured. "
                "Set REDIS_URL environment variable for Redis/ElastiCache connection."
            )

        _redis_client = redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=settings.REDIS_MAX_CONNECTIONS,
            socket_connect_timeout=settings.REDIS_SOCKET_CONNECT_TIMEOUT,
            socket_keepalive=settings.REDIS_SOCKET_KEEPALIVE,
        )
        logger.info(
            f"Redis client initialized (max_connections={settings.REDIS_MAX_CONNECTIONS})"
        )

    return _redis_client


async def close_redis() -> None:
    """Close Redis connection on shutdown."""
    global _redis_client

    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None
        logger.info("Redis client closed")


async def publish_event(channel: str, event: dict) -> int:
    """
    Publish an event to a Redis channel.

    Args:
        channel: Channel name (e.g., "turn:{turn_id}")
        event: Event data to publish

    Returns:
        Number of subscribers that received the message
    """
    client = await get_redis()
    message = json.dumps(event)
    return await client.publish(channel, message)


async def subscribe_to_channel(
    channel: str,
    timeout_seconds: float = 180.0,  # 3 minute max wait (safety net)
    poll_interval: float = 5.0,  # Check every 5 seconds
) -> AsyncIterator[dict]:
    """
    Subscribe to a Redis channel and yield events with timeout.

    Args:
        channel: Channel name to subscribe to
        timeout_seconds: Maximum total time to wait for completion
        poll_interval: How often to check for messages (allows for timeout checks)

    Yields:
        Event dictionaries as they arrive

    Note:
        Yields a timeout event if max wait time exceeded.
    """
    import time

    client = await get_redis()
    pubsub: PubSub = client.pubsub()
    start_time = time.time()

    try:
        await pubsub.subscribe(channel)
        logger.debug(f"Subscribed to channel: {channel}")

        while True:
            # Check for timeout
            elapsed = time.time() - start_time
            if elapsed > timeout_seconds:
                logger.warning(
                    f"SSE subscription timeout after {elapsed:.1f}s for channel: {channel}"
                )
                yield {
                    "event": "error",
                    "message": "Request timed out. Please try again.",
                }
                break

            # Get message with timeout (non-blocking)
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=poll_interval
            )

            if message is None:
                # No message received within poll_interval, loop to check timeout
                continue

            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    yield data

                    # Check for completion/error event to stop iteration
                    if data.get("event") in ("complete", "error"):
                        break
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON in Redis message: {message['data']}")
                    continue

    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        logger.debug(f"Unsubscribed from channel: {channel}")


class RedisHealthCheck:
    """Health check for Redis connection."""

    @staticmethod
    async def is_healthy() -> bool:
        """
        Check if Redis connection is healthy.

        Returns:
            True if Redis is reachable and responding
        """
        try:
            client = await get_redis()
            await client.ping()
            return True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False
