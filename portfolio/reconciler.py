"""Exchange reconciliation — sync local state with actual exchange balances."""

import asyncio
import logging

from execution.alpaca_adapter import AlpacaAdapter
from execution.binance_adapter import BinanceAdapter
from shared.redis_client import RedisClient

logger = logging.getLogger(__name__)


def _session_channel(session_id: str, channel: str) -> str:
    """Build session-namespaced Redis key."""
    if session_id:
        return f"session:{session_id}:{channel}"
    return channel


class Reconciler:
    """Periodically compares local portfolio state with exchange reality.

    NOTE: Not currently wired into V2 SessionPipeline. Only used by the
    legacy run_execution.py script. Session-aware for future integration.
    """

    def __init__(self, config: dict, redis: RedisClient, session_id: str = ""):
        self._config = config
        self._redis = redis
        self._session_id = session_id
        self._interval = config.get("portfolio", {}).get("reconcile_interval_sec", 60)
        self._running = False
        self._binance: BinanceAdapter | None = None
        self._alpaca: AlpacaAdapter | None = None

    async def start(self) -> None:
        """Connect adapters and start reconciliation loop."""
        if self._config.get("binance", {}).get("api_key"):
            self._binance = BinanceAdapter(self._config)
            await self._binance.connect()

        if self._config.get("alpaca", {}).get("api_key"):
            self._alpaca = AlpacaAdapter(self._config)
            await self._alpaca.connect()

        self._running = True
        logger.info("Reconciler started (interval=%ds)", self._interval)

        while self._running:
            await asyncio.sleep(self._interval)
            await self._reconcile()

    async def stop(self) -> None:
        self._running = False
        if self._binance:
            await self._binance.disconnect()
        if self._alpaca:
            await self._alpaca.disconnect()
        logger.info("Reconciler stopped")

    async def _reconcile(self) -> None:
        """Compare local state with exchange and log discrepancies."""
        local_state = await self._redis.get_flag(
            _session_channel(self._session_id, "portfolio:state")
        )
        if not local_state:
            return

        local_symbols = set(local_state.get("position_symbols", []))

        # Reconcile Binance
        if self._binance:
            try:
                exchange_positions = await self._binance.get_positions()
                exchange_symbols = {
                    p["symbol"] for p in exchange_positions if abs(p.get("quantity", 0)) > 0.0001
                }
                self._check_drift("Binance", local_symbols, exchange_symbols)
            except Exception:
                logger.exception("Binance reconciliation failed")

        # Reconcile Alpaca
        if self._alpaca:
            try:
                exchange_positions = await self._alpaca.get_positions()
                exchange_symbols = {
                    p["symbol"] for p in exchange_positions if abs(p.get("quantity", 0)) > 0.0001
                }
                self._check_drift("Alpaca", local_symbols, exchange_symbols)
            except Exception:
                logger.exception("Alpaca reconciliation failed")

    def _check_drift(
        self, exchange: str, local: set[str], remote: set[str]
    ) -> None:
        missing_local = remote - local
        missing_remote = local - remote

        if missing_local:
            logger.warning(
                "[%s] Positions on exchange but not tracked locally: %s",
                exchange, missing_local,
            )
        if missing_remote:
            logger.warning(
                "[%s] Positions tracked locally but not on exchange: %s",
                exchange, missing_remote,
            )
        if not missing_local and not missing_remote:
            logger.debug("[%s] Reconciliation OK", exchange)
