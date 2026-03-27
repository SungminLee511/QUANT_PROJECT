"""Redis-backed emergency kill switch for halting all trading.

State is also persisted to the DB so it survives Redis restarts (BUG-73).
On startup, call ``restore_from_db()`` to re-activate if needed.
"""

import logging
from datetime import datetime, timezone

from shared.redis_client import RedisClient

logger = logging.getLogger(__name__)


class KillSwitch:
    def __init__(self, redis: RedisClient, key: str = "risk:kill_switch",
                 session_id: str = ""):
        self._redis = redis
        self._key = key
        self._session_id = session_id

    async def is_active(self) -> bool:
        """Check if the kill switch is currently active."""
        state = await self._redis.get_flag(self._key)
        return bool(state and state.get("active", False))

    async def activate(self, reason: str = "Manual activation") -> None:
        """Activate the kill switch. All signals will be rejected."""
        now = datetime.now(timezone.utc)
        await self._redis.set_flag(
            self._key,
            {
                "active": True,
                "reason": reason,
                "activated_at": now.isoformat(),
            },
        )
        logger.warning("Kill switch ACTIVATED: %s", reason)

        # Persist to DB for durability (BUG-73)
        await self._persist_event(active=True, reason=reason, timestamp=now)

    async def deactivate(self) -> None:
        """Deactivate the kill switch. Trading resumes."""
        await self._redis.delete_flag(self._key)
        logger.info("Kill switch DEACTIVATED")

        # Persist to DB for audit trail (BUG-73)
        await self._persist_event(active=False, reason="Deactivated")

    async def get_state(self) -> dict:
        """Return current kill switch state."""
        state = await self._redis.get_flag(self._key)
        if state is None:
            return {"active": False}
        return state

    async def restore_from_db(self) -> bool:
        """Restore kill switch state from DB if Redis lost it.

        Returns True if kill switch was restored as active.
        """
        if not self._session_id:
            return False

        try:
            from db.session import get_session
            from db.models import KillSwitchEvent
            from sqlalchemy import select

            async with get_session() as session:
                stmt = (
                    select(KillSwitchEvent)
                    .where(KillSwitchEvent.session_id == self._session_id)
                    .order_by(KillSwitchEvent.timestamp.desc())
                    .limit(1)
                )
                result = await session.execute(stmt)
                event = result.scalar_one_or_none()

            if event and event.active:
                # Redis lost the state — restore it
                await self._redis.set_flag(
                    self._key,
                    {
                        "active": True,
                        "reason": event.reason,
                        "activated_at": event.timestamp.isoformat(),
                        "restored_from_db": True,
                    },
                )
                logger.warning(
                    "Kill switch RESTORED from DB: %s (originally activated %s)",
                    event.reason, event.timestamp.isoformat(),
                )
                return True

        except Exception:
            logger.exception("Failed to restore kill switch from DB (session=%s)", self._session_id)

        return False

    async def _persist_event(self, active: bool, reason: str,
                             timestamp: datetime | None = None) -> None:
        """Write kill switch event to DB for durability."""
        if not self._session_id:
            return  # Can't persist without session context

        try:
            from db.session import get_session
            from db.models import KillSwitchEvent

            async with get_session() as session:
                event = KillSwitchEvent(
                    session_id=self._session_id,
                    active=active,
                    reason=reason,
                    timestamp=timestamp or datetime.now(timezone.utc),
                )
                session.add(event)
        except Exception:
            logger.exception(
                "Failed to persist kill switch event to DB (session=%s)",
                self._session_id,
            )
