"""Redis-backed emergency kill switch for halting all trading."""

import logging
from datetime import datetime, timezone

from shared.redis_client import RedisClient

logger = logging.getLogger(__name__)


class KillSwitch:
    def __init__(self, redis: RedisClient, key: str = "risk:kill_switch"):
        self._redis = redis
        self._key = key

    async def is_active(self) -> bool:
        """Check if the kill switch is currently active."""
        state = await self._redis.get_flag(self._key)
        return bool(state and state.get("active", False))

    async def activate(self, reason: str = "Manual activation") -> None:
        """Activate the kill switch. All signals will be rejected."""
        await self._redis.set_flag(
            self._key,
            {
                "active": True,
                "reason": reason,
                "activated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        logger.warning("Kill switch ACTIVATED: %s", reason)

    async def deactivate(self) -> None:
        """Deactivate the kill switch. Trading resumes."""
        await self._redis.delete_flag(self._key)
        logger.info("Kill switch DEACTIVATED")

    async def get_state(self) -> dict:
        """Return current kill switch state."""
        state = await self._redis.get_flag(self._key)
        if state is None:
            return {"active": False}
        return state
