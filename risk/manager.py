"""Risk check pipeline — consumes signals, applies checks, emits approved orders."""

import asyncio
import logging

from shared.enums import Exchange, OrderType, Side
from shared.redis_client import RedisClient
from shared.schemas import AlertMessage, LogEntry, OrderRequest, RiskCheckResult, TradeSignal
from risk.kill_switch import KillSwitch
from risk.limits import (
    check_daily_loss,
    check_drawdown,
    check_kill_switch,
    check_max_positions,
    check_position_size,
)

logger = logging.getLogger(__name__)


class RiskManager:
    """V1 LEGACY — subscribes to strategy signals, runs risk checks, forwards approved orders.

    .. deprecated::
        V2 SessionPipeline calls ``check_portfolio_risk()`` from ``risk.limits``
        directly.  This class is only used by ``scripts/run_execution.py``
        (V1 standalone runner).  Do NOT use in new code.
    """

    def __init__(self, config: dict, redis: RedisClient, session_id: str = ""):
        self._config = config
        self._redis = redis
        self._session_id = session_id
        self._kill_switch = KillSwitch(
            redis, config.get("risk", {}).get("kill_switch_key", "risk:kill_switch")
        )
        self._running = False

        channels = config.get("redis", {}).get("channels", {})
        self._signal_channel = channels.get("signals", "strategy:signals")
        self._order_channel = channels.get("orders", "execution:orders")
        self._alert_channel = channels.get("alerts", "monitoring:alerts")
        self._logs_channel = channels.get("logs", "")

        # Portfolio state cache — updated by portfolio tracker via Redis
        self._portfolio_state: dict = {
            "total_equity": 10000.0,  # Default starting equity
            "peak_equity": 10000.0,
            "day_start_equity": 10000.0,
            "daily_pnl": 0.0,
            "open_positions": 0,
            "position_symbols": set(),
            "prices": {},
        }

    async def start(self) -> None:
        """Subscribe to signals and start processing."""
        self._running = True
        await self._redis.subscribe(
            self._signal_channel,
            self._on_signal,
        )
        sid = f" (session={self._session_id})" if self._session_id else ""
        logger.info("Risk manager started%s", sid)

        while self._running:
            # Periodically refresh portfolio state from Redis
            await self._refresh_portfolio_state()
            await asyncio.sleep(5)

    async def stop(self) -> None:
        self._running = False
        sid = f" (session={self._session_id})" if self._session_id else ""
        logger.info("Risk manager stopped%s", sid)

    async def _on_signal(self, data: dict) -> None:
        """Process an incoming trade signal through the risk pipeline."""
        try:
            signal = TradeSignal.model_validate(data)
            result = await self._check_all(signal)

            if result.approved:
                order = self._signal_to_order(signal)
                await self._redis.publish(self._order_channel, order)
                await self._publish_log(
                    "risk_approve", signal.symbol,
                    f"APPROVED {signal.signal.value.upper()} {signal.symbol} → order qty={order.quantity:.6f}",
                    metadata={"signal": signal.signal.value, "quantity": order.quantity},
                )
                logger.info(
                    "Signal APPROVED: %s %s from %s",
                    signal.signal.value, signal.symbol, signal.strategy_id,
                )
            else:
                await self._publish_log(
                    "risk_reject", signal.symbol,
                    f"REJECTED {signal.signal.value.upper()} {signal.symbol} — {result.reason}",
                    level="warning",
                    metadata={"signal": signal.signal.value, "reason": result.reason},
                )
                logger.warning(
                    "Signal REJECTED: %s %s — %s",
                    signal.signal.value, signal.symbol, result.reason,
                )
                await self._redis.publish(
                    self._alert_channel,
                    AlertMessage(
                        level="warning",
                        message=f"Signal rejected: {signal.symbol} {signal.signal.value} — {result.reason}",
                        source="risk",
                    ),
                )

                # Auto-activate kill switch on drawdown or daily loss breach
                if "drawdown" in result.reason.lower() or "daily loss" in result.reason.lower():
                    await self._kill_switch.activate(result.reason)

        except Exception:
            logger.exception("Error processing signal")

    async def _publish_log(self, event_type: str, symbol: str, message: str,
                          level: str = "info", metadata: dict | None = None) -> None:
        if not self._logs_channel:
            return
        try:
            entry = LogEntry(
                event_type=event_type, session_id=self._session_id,
                symbol=symbol, message=message, level=level,
                source="risk", metadata=metadata or {},
            )
            await self._redis.publish(self._logs_channel, entry)
        except Exception:
            pass

    async def _check_all(self, signal: TradeSignal) -> RiskCheckResult:
        """Run all risk checks sequentially."""
        # 1. Kill switch (async — reads Redis)
        approved, reason = await check_kill_switch(self._redis, self._config)
        if not approved:
            return RiskCheckResult(approved=False, reason=reason, original_signal=signal)

        # 2. Drawdown check
        approved, reason = check_drawdown(self._portfolio_state, self._config)
        if not approved:
            return RiskCheckResult(approved=False, reason=reason, original_signal=signal)

        # 3. Daily loss check
        approved, reason = check_daily_loss(self._portfolio_state, self._config)
        if not approved:
            return RiskCheckResult(approved=False, reason=reason, original_signal=signal)

        # 4. Max positions
        approved, reason = check_max_positions(signal, self._portfolio_state, self._config)
        if not approved:
            return RiskCheckResult(approved=False, reason=reason, original_signal=signal)

        # 5. Position size
        approved, reason = check_position_size(signal, self._portfolio_state, self._config)
        if not approved:
            return RiskCheckResult(approved=False, reason=reason, original_signal=signal)

        return RiskCheckResult(approved=True, reason="All checks passed", original_signal=signal)

    def _signal_to_order(self, signal: TradeSignal) -> OrderRequest:
        """Convert an approved TradeSignal into an OrderRequest."""
        # Determine exchange from symbol convention
        # Crypto pairs typically end in USDT/BTC, equities are short tickers
        symbol = signal.symbol.upper()
        if symbol.endswith("USDT") or symbol.endswith("BTC") or symbol.endswith("ETH"):
            exchange = Exchange.BINANCE
        else:
            exchange = Exchange.ALPACA

        # Simple sizing: use max_position_pct of equity
        max_pct = self._config.get("risk", {}).get("max_position_pct", 0.10)
        equity = self._portfolio_state.get("total_equity", 10000)
        price = self._portfolio_state.get("prices", {}).get(signal.symbol, 1)
        quantity = (equity * max_pct * signal.strength) / max(price, 0.01)

        side = Side.BUY if signal.signal.value == "buy" else Side.SELL

        return OrderRequest(
            symbol=signal.symbol,
            side=side,
            quantity=round(quantity, 8),
            order_type=OrderType.MARKET,
            exchange=exchange,
            strategy_id=signal.strategy_id,
        )

    async def _refresh_portfolio_state(self) -> None:
        """Pull latest portfolio state from Redis (set by portfolio tracker)."""
        try:
            # Use session-namespaced key if available (set by session manager)
            state_key = self._config.get("risk", {}).get(
                "portfolio_state_key", "portfolio:state"
            )
            state = await self._redis.get_flag(state_key)
            if state:
                self._portfolio_state.update(state)
                # Convert position_symbols back to a set
                if "position_symbols" in self._portfolio_state:
                    self._portfolio_state["position_symbols"] = set(
                        self._portfolio_state["position_symbols"]
                    )
        except Exception:
            logger.warning(
                "Failed to refresh portfolio state from Redis (session=%s), "
                "using cached state — risk decisions may be based on stale data",
                self._session_id,
                exc_info=True,
            )
