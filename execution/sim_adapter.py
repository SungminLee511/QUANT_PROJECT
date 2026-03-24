"""Simulation exchange adapter — instant fills at market price, no real orders.

Used for both Binance Sim and Alpaca Sim sessions. Tracks a virtual portfolio
(cash + positions) and fills all market orders instantly at the last known price.
"""

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
    ):
        self._session_id = session_id
        self._exchange = exchange
        self._redis = redis
        self._cash = starting_budget
        self._starting_budget = starting_budget
        self._positions: dict[str, dict] = {}  # {symbol: {quantity, avg_price}}
        self._last_prices: dict[str, float] = {}
        self._orders: dict[str, dict] = {}  # {order_id: order_info}
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
            self._last_prices[symbol] = float(price)

    async def place_order(self, order_request: OrderRequest) -> str:
        """Instantly fill the order at last known market price."""
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
            if cost > self._cash:
                # Adjust quantity to what we can afford
                quantity = self._cash / price
                if quantity <= 0:
                    raise ValueError(f"Insufficient cash for {symbol}")
                cost = price * quantity

            # Update sim portfolio
            pos = self._positions.get(symbol, {"quantity": 0.0, "avg_price": 0.0})
            old_value = pos["quantity"] * pos["avg_price"]
            new_value = quantity * price
            new_qty = pos["quantity"] + quantity
            pos["avg_price"] = (old_value + new_value) / new_qty if new_qty > 0 else 0
            pos["quantity"] = new_qty
            self._positions[symbol] = pos
            self._cash -= cost

        elif order_request.side == Side.SELL:
            pos = self._positions.get(symbol, {"quantity": 0.0, "avg_price": 0.0})
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

        # Record the order
        self._orders[order_id] = {
            "symbol": symbol,
            "side": order_request.side.value,
            "quantity": quantity,
            "price": price,
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
        """Return simulated cash balance."""
        total_value = self._cash + sum(
            pos["quantity"] * self._last_prices.get(sym, pos["avg_price"])
            for sym, pos in self._positions.items()
            if pos["quantity"] > 0
        )
        return {
            "cash": self._cash,
            "total_equity": total_value,
            "positions_value": total_value - self._cash,
        }

    async def get_positions(self) -> list:
        """Return simulated positions."""
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
            if pos["quantity"] > 0
        ]

    def get_last_price(self, symbol: str) -> float:
        """Get the last known price for a symbol."""
        return self._last_prices.get(symbol, 0.0)
