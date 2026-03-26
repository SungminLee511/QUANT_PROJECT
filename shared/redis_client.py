"""Redis helper: async pub/sub, key-value flags, connection pooling."""

import asyncio
import json
import logging
from typing import Any, Callable, Optional, Type

import redis.asyncio as aioredis
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class RedisClient:
    """Async Redis client with pub/sub and flag helpers."""

    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0):
        self._host = host
        self._port = port
        self._db = db
        self._pool: Optional[aioredis.ConnectionPool] = None
        self._redis: Optional[aioredis.Redis] = None
        self._pubsub: Optional[aioredis.client.PubSub] = None
        self._subscriptions: dict[str, list[Callable]] = {}
        self._listener_task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        """Establish Redis connection with connection pooling."""
        self._pool = aioredis.ConnectionPool.from_url(
            f"redis://{self._host}:{self._port}/{self._db}",
            max_connections=20,
            decode_responses=True,
        )
        self._redis = aioredis.Redis(connection_pool=self._pool)
        await self._redis.ping()
        logger.info("Redis connected to %s:%s/%s", self._host, self._port, self._db)

    async def disconnect(self) -> None:
        """Close Redis connections."""
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()
        if self._pool:
            await self._pool.disconnect()
        logger.info("Redis disconnected")

    async def publish(self, channel: str, message: BaseModel) -> None:
        """Serialize a Pydantic model and publish to a channel."""
        data = message.model_dump_json()
        await self._redis.publish(channel, data)

    async def subscribe(
        self,
        channel: str,
        callback: Callable,
        model_class: Optional[Type[BaseModel]] = None,
    ) -> None:
        """Subscribe to a channel. Callback receives deserialized model or raw dict."""
        if self._pubsub is None:
            self._pubsub = self._redis.pubsub()

        await self._pubsub.subscribe(channel)

        if channel not in self._subscriptions:
            self._subscriptions[channel] = []
        self._subscriptions[channel].append((callback, model_class))

        # Start listener if not already running
        if self._listener_task is None or self._listener_task.done():
            self._listener_task = asyncio.create_task(self._listen())

    async def _listen(self) -> None:
        """Background listener for pub/sub messages.

        Dispatches callbacks as concurrent tasks so a slow subscriber
        on one session doesn't block others (ARCH-4).

        Auto-retries on error with exponential backoff (CONC-3).
        Re-subscribes to all channels after reconnecting.
        """
        backoff = 1.0
        max_backoff = 60.0

        while True:
            try:
                async for message in self._pubsub.listen():
                    backoff = 1.0  # reset on successful message
                    if message["type"] != "message":
                        continue
                    channel = message["channel"]
                    data = message["data"]

                    handlers = self._subscriptions.get(channel, [])
                    for callback, model_class in handlers:
                        asyncio.create_task(
                            self._dispatch(channel, callback, model_class, data)
                        )
                # listen() ended normally (e.g. unsubscribed) — exit loop
                break
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception(
                    "Redis listener error — retrying in %.1fs", backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

                # Re-subscribe to all channels after reconnect
                try:
                    if self._pubsub:
                        channels = list(self._subscriptions.keys())
                        if channels:
                            await self._pubsub.subscribe(*channels)
                            logger.info(
                                "Redis listener re-subscribed to %d channel(s)",
                                len(channels),
                            )
                except Exception:
                    logger.exception("Failed to re-subscribe — will retry")

    @staticmethod
    async def _dispatch(
        channel: str, callback: Callable, model_class: Optional[Type[BaseModel]], data: str
    ) -> None:
        """Parse a message and invoke the callback. Runs as an independent task."""
        try:
            if model_class is not None:
                parsed = model_class.model_validate_json(data)
            else:
                parsed = json.loads(data)
            await callback(parsed)
        except Exception:
            logger.exception("Error in handler for channel %s", channel)

    # ── Flag helpers (for kill switch, state flags) ──

    async def set_flag(self, key: str, value: Any) -> None:
        """Set a Redis key to a JSON-serialized value."""
        await self._redis.set(key, json.dumps(value))

    async def get_flag(self, key: str) -> Any:
        """Get a JSON-deserialized value from a Redis key."""
        raw = await self._redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def delete_flag(self, key: str) -> None:
        """Delete a Redis key."""
        await self._redis.delete(key)

    @property
    def redis(self) -> aioredis.Redis:
        """Access the underlying Redis client."""
        return self._redis


def session_channel(session_id: str, base_channel: str) -> str:
    """Build a session-namespaced Redis channel: session:{id}:{base}."""
    return f"session:{session_id}:{base_channel}"


def create_redis_client(config: dict) -> RedisClient:
    """Create a RedisClient from config dict."""
    redis_cfg = config.get("redis", {})
    return RedisClient(
        host=redis_cfg.get("host", "localhost"),
        port=redis_cfg.get("port", 6379),
        db=redis_cfg.get("db", 0),
    )
