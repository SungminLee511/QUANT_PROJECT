"""Simulation exchange adapter — instant fills at market price, no real orders.

Used for both Binance Sim and Alpaca Sim sessions. Tracks a virtual portfolio
(cash + positions) and fills all market orders instantly at the last known price.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from execution.base_adapter import BaseExchangeAdapter
from shared.enums import Exchange, OrderStatus, Side
from shared.redis_client import RedisClient, session_channel
from shared.schemas import OrderRequest, OrderUpdate

logger = logging.getLogger(__name__)


class SimulationAdapter(BaseExchangeAdapter):
    """Simulated exchange that fills all orders instantly at market price."""

    def __init__(
        self,
        session_id: str,
        starting_budget: float,
        exchange: Exchange,
        redis: RedisClient,
        strategy_mode: str = "rebalance",
        commission_pct: float = 0.0,
    ):
        self._session_id = session_id
        self._exchange = exchange
        self._redis = redis
        self._cash = starting_budget
        self._starting_budget = starting_budget
        self._strategy_mode = strategy_mode
        self._commission_rate = commission_pct / 100.0  # convert % to fraction
        self._total_fees: float = 0.0
        self._positions: dict[str, dict] = {}  # {symbol: {quantity, avg_price}}
        self._last_prices: dict[str, float] = {}
        self._orders: dict[str, dict] = {}  # {order_id: order_info}
        self._lock = asyncio.Lock()  # Guards _cash, _positions, _last_prices
        self._market_channel = session_channel(session_id, "market:ticks")
        self._running = False

    async def start_price_listener(self) -> None:
        """Subscribe to market data to track latest prices for sim fills."""
        self._running = True
        await self._redis.subscribe(
            self._market_channel,
            self._on_price_update,
        )
        logger.info(
            "SimulationAdapter started (session=%s, exchange=%s, budget=%.2f)",
            self._session_id,
            self._exchange.value,
            self._starting_budget,
        )

    async def _on_price_update(self, data: dict) -> None:
        """Track last known price per symbol."""
        symbol = data.get("symbol")
        price = data.get("price") or data.get("close")
        if symbol and price:
            async with self._lock:
                self._last_prices[symbol] = float(price)

    async def place_order(self, order_request: OrderRequest) -> str:
        """Instantly fill the order at last known market price."""
        async with self._lock:
            order_id = f"sim-{uuid.uuid4().hex[:12]}"
            symbol = order_request.symbol
            price = self._last_prices.get(symbol, 0)

            if price <= 0:
                logger.warning(
                    "SimAdapter: no price for %s, rejecting order (session=%s)",
                    symbol,
                    self._session_id,
                )
                raise ValueError(f"No market price available for {symbol}")

            quantity = order_request.quantity
            cost = price * quantity

            if order_request.side == Side.BUY:
                pos = self._positions.get(symbol, {"quantity": 0.0, "avg_price": 0.0})

                if self._strategy_mode == "long_short" and pos["quantity"] < 0:
                    # Covering a short — don't cap by cash.  The trader is
                    # obligated to cover; capping makes shorts unclosable
                    # when cash is depleted, breaking kill-switch flatten.
                    # Cash can go temporarily negative (margin-like).
                    self._cash -= cost
                    new_qty = pos["quantity"] + quantity
                    if abs(new_qty) <= 0.0001:
                        new_qty = 0.0
                        pos["avg_price"] = 0.0
                    elif new_qty > 0:
                        pos["avg_price"] = price
                    pos["quantity"] = new_qty
                    self._positions[symbol] = pos
                else:
                    # Normal buy (long position)
                    if cost > self._cash:
                        quantity = self._cash / price
                        if quantity < 0.0001:
                            raise ValueError(f"Insufficient cash for {symbol}")
                        cost = price * quantity

                    old_value = pos["quantity"] * pos["avg_price"]
                    new_value = quantity * price
                    new_qty = pos["quantity"] + quantity
                    pos["avg_price"] = (old_value + new_value) / new_qty if new_qty > 0 else 0
                    pos["quantity"] = new_qty
                    self._positions[symbol] = pos
                    self._cash -= cost

            elif order_request.side == Side.SELL:
                pos = self._positions.get(symbol, {"quantity": 0.0, "avg_price": 0.0})
                if self._strategy_mode == "long_short":
                    # Allow short selling — position can go negative
                    pos["quantity"] -= quantity
                    self._cash += quantity * price
                    # Update avg_price for short positions
                    if pos["quantity"] < 0:
                        pos["avg_price"] = price  # simplified: use latest sell price
                    elif abs(pos["quantity"]) <= 0.0001:
                        pos["quantity"] = 0.0
                        pos["avg_price"] = 0.0
                    self._positions[symbol] = pos
                else:
                    # Long-only: cap sell to current holdings
                    sell_qty = min(quantity, pos["quantity"])
                    if sell_qty <= 0:
                        raise ValueError(f"No position in {symbol} to sell")
                    pos["quantity"] -= sell_qty
                    self._cash += sell_qty * price
                    if pos["quantity"] <= 0.0001:
                        pos["quantity"] = 0.0
                        pos["avg_price"] = 0.0
                    self._positions[symbol] = pos
                    quantity = sell_qty

            # Apply commission fee (deducted from cash regardless of buy/sell)
            fee = abs(quantity * price) * self._commission_rate
            self._cash -= fee
            self._total_fees += fee

            # Record the order
            self._orders[order_id] = {
                "symbol": symbol,
                "side": order_request.side.value,
                "quantity": quantity,
                "price": price,
                "fee": fee,
                "status": OrderStatus.FILLED.value,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            logger.info(
                "SimAdapter FILLED: %s %s %.6f @ %.2f (session=%s, cash=%.2f)",
                order_request.side.value,
                symbol,
                quantity,
                price,
                self._session_id,
                self._cash,
            )

            return order_id

    async def cancel_order(self, external_order_id: str) -> bool:
        """Sim orders are instant fills — nothing to cancel."""
        return True

    async def get_order_status(self, external_order_id: str) -> OrderUpdate:
        """All sim orders are immediately filled."""
        order = self._orders.get(external_order_id, {})
        return OrderUpdate(
            order_id=external_order_id,
            external_id=external_order_id,
            symbol=order.get("symbol", ""),
            side=Side(order.get("side", "buy")),
            status=OrderStatus.FILLED,
            filled_qty=order.get("quantity", 0),
            avg_price=order.get("price", 0),
            exchange=self._exchange,
            session_id=self._session_id,
        )

    async def get_balances(self) -> dict:
        """Return simulated cash balance.

        For short positions (negative qty), the position value is negative
        (qty * price < 0), which correctly reduces total equity.
        """
        async with self._lock:
            total_value = self._cash + sum(
                pos["quantity"] * self._last_prices.get(sym, pos["avg_price"])
                for sym, pos in self._positions.items()
                if abs(pos["quantity"]) > 0.0001
            )
            return {
                "cash": self._cash,
                "total_equity": total_value,
                "positions_value": total_value - self._cash,
                "total_fees": self._total_fees,
            }

    async def get_positions(self) -> list:
        """Return simulated positions."""
        async with self._lock:
            return [
                {
                    "symbol": sym,
                    "quantity": pos["quantity"],
                    "avg_entry_price": pos["avg_price"],
                    "current_price": self._last_prices.get(sym, pos["avg_price"]),
                    "unrealized_pnl": pos["quantity"] * (
                        self._last_prices.get(sym, pos["avg_price"]) - pos["avg_price"]
                    ),
                }
                for sym, pos in self._positions.items()
                if abs(pos["quantity"]) > 0.0001
            ]

    async def get_positions_snapshot(self) -> dict[str, dict]:
        """Return a thread-safe copy of positions dict for external reads."""
        async with self._lock:
            return {
                sym: {"quantity": pos["quantity"], "avg_price": pos["avg_price"]}
                for sym, pos in self._positions.items()
            }

    def get_last_price(self, symbol: str) -> float:
        """Get the last known price for a symbol."""
        return self._last_prices.get(symbol, 0.0)
