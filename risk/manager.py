"""Risk check pipeline — consumes signals, applies checks, emits approved orders."""

import asyncio
import logging

from shared.enums import Exchange, OrderType, Side, round_quantity
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
            redis, config.get("risk", {}).get("kill_switch_key", "risk:kill_switch"),
            session_id=session_id,
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
                if order is None:
                    # BUG-76: sizing validation failed
                    await self._publish_log(
                        "risk_reject", signal.symbol,
                        f"REJECTED {signal.signal.value.upper()} {signal.symbol} — order sizing failed",
                        level="warning",
                        metadata={"signal": signal.signal.value, "reason": "sizing_failed"},
                    )
                    return
                # CONC-7: Re-check kill switch immediately before order emission
                # to minimize race window between check and action
                ks_ok, ks_reason = await check_kill_switch(self._redis, self._config)
                if not ks_ok:
                    await self._publish_log(
                        "risk_reject", signal.symbol,
                        f"REJECTED {signal.signal.value.upper()} {signal.symbol} — {ks_reason} (late check)",
                        level="warning",
                        metadata={"signal": signal.signal.value, "reason": ks_reason},
                    )
                    return
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

                # BUG-74: Use structured check_id instead of fragile string matching
                _KILL_SWITCH_CHECKS = {"drawdown", "daily_loss"}
                if result.check_id in _KILL_SWITCH_CHECKS:
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
            logger.debug("Failed to publish risk log", exc_info=True)

    async def _check_all(self, signal: TradeSignal) -> RiskCheckResult:
        """Run all risk checks sequentially."""
        # 1. Kill switch (async — reads Redis)
        approved, reason = await check_kill_switch(self._redis, self._config)
        if not approved:
            return RiskCheckResult(approved=False, reason=reason, check_id="kill_switch", original_signal=signal)

        # 2. Drawdown check
        approved, reason = check_drawdown(self._portfolio_state, self._config)
        if not approved:
            return RiskCheckResult(approved=False, reason=reason, check_id="drawdown", original_signal=signal)

        # 3. Daily loss check
        approved, reason = check_daily_loss(self._portfolio_state, self._config)
        if not approved:
            return RiskCheckResult(approved=False, reason=reason, check_id="daily_loss", original_signal=signal)

        # 4. Max positions
        approved, reason = check_max_positions(signal, self._portfolio_state, self._config)
        if not approved:
            return RiskCheckResult(approved=False, reason=reason, check_id="max_positions", original_signal=signal)

        # 5. Position size
        approved, reason = check_position_size(signal, self._portfolio_state, self._config)
        if not approved:
            return RiskCheckResult(approved=False, reason=reason, check_id="position_size", original_signal=signal)

        return RiskCheckResult(approved=True, reason="All checks passed", original_signal=signal)

    def _signal_to_order(self, signal: TradeSignal) -> OrderRequest | None:
        """Convert an approved TradeSignal into an OrderRequest.

        Returns None if the order cannot be safely constructed (BUG-76).
        """
        # ARCH-9: Use exchange hint from signal if available, fall back to suffix matching
        symbol = signal.symbol.upper()
        if signal.exchange:
            try:
                exchange = Exchange(signal.exchange.lower())
            except ValueError:
                logger.warning(
                    "Unknown exchange '%s' in signal for %s, falling back to suffix detection",
                    signal.exchange, symbol,
                )
                exchange = self._detect_exchange(symbol)
        else:
            exchange = self._detect_exchange(symbol)

        # Simple sizing: use max_position_pct of equity
        max_pct = self._config.get("risk", {}).get("max_position_pct", 0.10)
        equity = self._portfolio_state.get("total_equity", 10000)
        price = self._portfolio_state.get("prices", {}).get(signal.symbol)

        # BUG-76: Validate inputs before computing quantity
        if price is None or price <= 0:
            logger.warning(
                "Cannot size order for %s: price=%s (session=%s)",
                signal.symbol, price, self._session_id,
            )
            return None
        if equity <= 0:
            logger.warning(
                "Cannot size order for %s: equity=%.2f (session=%s)",
                signal.symbol, equity, self._session_id,
            )
            return None

        quantity = (equity * max_pct * signal.strength) / price
        quantity = round_quantity(quantity, exchange)

        # BUG-76: Reject dust and unreasonably large quantities
        if quantity <= 0:
            logger.warning(
                "Computed quantity <= 0 for %s (qty=%.8f, session=%s)",
                signal.symbol, quantity, self._session_id,
            )
            return None

        # Cap at 10x the intended notional as a sanity guard
        max_qty = (equity * max_pct * 10) / price
        if quantity > max_qty:
            logger.warning(
                "Quantity %.4f exceeds safety cap %.4f for %s (session=%s)",
                quantity, max_qty, signal.symbol, self._session_id,
            )
            return None

        # R3-11: "hold" signals should not generate orders.
        # Previously the ternary mapped hold → SELL, liquidating positions.
        if signal.signal.value == "hold":
            return None
        side = Side.BUY if signal.signal.value == "buy" else Side.SELL

        return OrderRequest(
            symbol=signal.symbol,
            side=side,
            quantity=quantity,
            order_type=OrderType.MARKET,
            exchange=exchange,
            strategy_id=signal.strategy_id,
        )

    @staticmethod
    def _detect_exchange(symbol: str) -> Exchange:
        """Fallback exchange detection from symbol suffix.

        ARCH-9: This is brittle — prefer setting ``exchange`` on the TradeSignal
        directly.  Used only as a fallback when the signal has no exchange hint.
        """
        if symbol.endswith("USDT") or symbol.endswith("BTC") or symbol.endswith("ETH"):
            return Exchange.BINANCE
        return Exchange.ALPACA

    async def _refresh_portfolio_state(self) -> None:
        """Pull latest portfolio state from Redis (set by portfolio tracker)."""
        try:
            # Use session-namespaced key if available (set by session manager)
            state_key = self._config.get("risk", {}).get(
                "portfolio_state_key", "portfolio:state"
            )
            state = await self._redis.get_flag(state_key)
            if state is None:
                if not getattr(self, "_warned_no_state", False):
                    logger.warning(
                        "Portfolio state key '%s' not found in Redis (session=%s) "
                        "— risk checks using cached/default state",
                        state_key, self._session_id,
                    )
                    self._warned_no_state = True
                return
            self._warned_no_state = False
            if state:
                self._portfolio_state.update(state)
                # Convert position_symbols back to a set (Redis returns lists)
                raw_syms = self._portfolio_state.get("position_symbols")
                if isinstance(raw_syms, (list, set, tuple)):
                    self._portfolio_state["position_symbols"] = set(raw_syms)
                elif raw_syms is None:
                    self._portfolio_state["position_symbols"] = set()
                else:
                    logger.warning(
                        "Unexpected position_symbols type %s — resetting to empty set",
                        type(raw_syms).__name__,
                    )
                    self._portfolio_state["position_symbols"] = set()
        except Exception:
            logger.warning(
                "Failed to refresh portfolio state from Redis (session=%s), "
                "using cached state — risk decisions may be based on stale data",
                self._session_id,
                exc_info=True,
            )
