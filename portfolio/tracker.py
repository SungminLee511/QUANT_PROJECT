"""Central position and balance tracker — consumes order updates, maintains state."""

import asyncio
import logging
from datetime import datetime, timezone

from db.models import Position as PositionModel, EquitySnapshot
from db.session import get_session
from shared.enums import OrderStatus, Side
from shared.redis_client import RedisClient, session_channel
from shared.schemas import OrderUpdate

logger = logging.getLogger(__name__)


class PortfolioTracker:
    """Tracks positions, balances, and publishes state to Redis."""

    def __init__(
        self,
        config: dict,
        redis: RedisClient,
        session_id: str = "",
        starting_cash: float = 10000.0,
    ):
        self._config = config
        self._redis = redis
        self._session_id = session_id
        self._running = False

        channels = config.get("redis", {}).get("channels", {})
        self._update_channel = channels.get("order_updates", "execution:updates")

        # In-memory position state: {symbol: {quantity, avg_entry_price, exchange}}
        self._positions: dict[str, dict] = {}
        self._cash: float = starting_cash
        self._peak_equity: float = starting_cash
        self._day_start_equity: float = starting_cash
        self._prices: dict[str, float] = {}  # Latest prices per symbol

        # State key — namespaced if session_id is set
        if session_id:
            self._state_key = session_channel(session_id, "portfolio:state")
        else:
            self._state_key = "portfolio:state"

    async def start(self) -> None:
        """Subscribe to order updates and start snapshot loop."""
        self._running = True
        await self._redis.subscribe(self._update_channel, self._on_order_update)

        # Also subscribe to market data for price updates
        market_channel = self._config.get("redis", {}).get("channels", {}).get(
            "market_data", "market:ticks"
        )
        await self._redis.subscribe(market_channel, self._on_market_data)

        # Start equity snapshot task
        asyncio.create_task(self._snapshot_loop())
        # Start state publishing task
        asyncio.create_task(self._publish_state_loop())

        logger.info("Portfolio tracker started (session=%s, cash=%.2f)", self._session_id, self._cash)

        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        self._running = False
        logger.info("Portfolio tracker stopped (session=%s)", self._session_id)

    async def _on_order_update(self, data: dict) -> None:
        """Update positions based on order fill updates."""
        try:
            update = OrderUpdate.model_validate(data)

            if update.status not in (OrderStatus.FILLED, OrderStatus.PARTIAL):
                return
            if update.filled_qty <= 0 or update.avg_price <= 0:
                return

            symbol = update.symbol
            pos = self._positions.get(symbol, {
                "quantity": 0.0,
                "avg_entry_price": 0.0,
                "exchange": update.exchange.value,
            })

            if update.side == Side.BUY:
                # Update average entry price
                old_value = pos["quantity"] * pos["avg_entry_price"]
                new_value = update.filled_qty * update.avg_price
                new_qty = pos["quantity"] + update.filled_qty
                pos["avg_entry_price"] = (old_value + new_value) / new_qty if new_qty > 0 else 0
                pos["quantity"] = new_qty
                self._cash -= update.filled_qty * update.avg_price
            elif update.side == Side.SELL:
                pos["quantity"] -= update.filled_qty
                self._cash += update.filled_qty * update.avg_price
                if pos["quantity"] <= 0.0001:  # Effectively closed
                    pos["quantity"] = 0.0
                    pos["avg_entry_price"] = 0.0

            self._positions[symbol] = pos
            self._prices[symbol] = update.avg_price

            await self._persist_position(symbol, pos)

            logger.info(
                "Position updated: %s qty=%.4f avg_price=%.2f (session=%s)",
                symbol, pos["quantity"], pos["avg_entry_price"], self._session_id,
            )

        except Exception:
            logger.exception("Error processing order update")

    async def _on_market_data(self, data: dict) -> None:
        """Update latest prices from market data."""
        try:
            symbol = data.get("symbol")
            price = data.get("price") or data.get("close")
            if symbol and price:
                self._prices[symbol] = float(price)
        except Exception:
            logger.debug("Failed to parse market data update", exc_info=True)

    def get_total_equity(self) -> float:
        """Cash + sum of all position values at current prices."""
        positions_value = sum(
            pos["quantity"] * self._prices.get(symbol, pos["avg_entry_price"])
            for symbol, pos in self._positions.items()
            if pos["quantity"] > 0
        )
        return self._cash + positions_value

    def get_positions_value(self) -> float:
        return sum(
            pos["quantity"] * self._prices.get(symbol, pos["avg_entry_price"])
            for symbol, pos in self._positions.items()
            if pos["quantity"] > 0
        )

    def get_all_positions(self) -> dict:
        return {
            symbol: {
                **pos,
                "current_price": self._prices.get(symbol, pos["avg_entry_price"]),
                "unrealized_pnl": pos["quantity"] * (
                    self._prices.get(symbol, pos["avg_entry_price"]) - pos["avg_entry_price"]
                ),
            }
            for symbol, pos in self._positions.items()
            if pos["quantity"] > 0
        }

    async def _publish_state_loop(self) -> None:
        """Publish portfolio state to Redis every 5 seconds for other services."""
        while self._running:
            try:
                equity = self.get_total_equity()
                self._peak_equity = max(self._peak_equity, equity)

                state = {
                    "total_equity": equity,
                    "peak_equity": self._peak_equity,
                    "day_start_equity": self._day_start_equity,
                    "daily_pnl": equity - self._day_start_equity,
                    "cash": self._cash,
                    "open_positions": sum(
                        1 for p in self._positions.values() if p["quantity"] > 0
                    ),
                    "positions": [
                        {"symbol": s, "quantity": p["quantity"], "avg_entry_price": p["avg_entry_price"]}
                        for s, p in self._positions.items()
                        if p["quantity"] > 0
                    ],
                    "position_symbols": [
                        s for s, p in self._positions.items() if p["quantity"] > 0
                    ],
                    "prices": self._prices,
                }
                await self._redis.set_flag(self._state_key, state)
            except Exception:
                logger.exception("Error publishing portfolio state")
            await asyncio.sleep(5)

    async def _snapshot_loop(self) -> None:
        """Store equity snapshots to DB every 60 seconds."""
        interval = self._config.get("portfolio", {}).get("reconcile_interval_sec", 60)
        while self._running:
            await asyncio.sleep(interval)
            if not self._session_id:
                continue  # Skip DB writes if no session (legacy mode)
            try:
                equity = self.get_total_equity()
                async with get_session() as session:
                    snapshot = EquitySnapshot(
                        session_id=self._session_id,
                        total_equity=equity,
                        cash=self._cash,
                        positions_value=self.get_positions_value(),
                    )
                    session.add(snapshot)
                logger.debug("Equity snapshot: %.2f (session=%s)", equity, self._session_id)
            except Exception:
                logger.exception("Error saving equity snapshot")

    async def _persist_position(self, symbol: str, pos: dict) -> None:
        """Upsert position to DB."""
        if not self._session_id:
            return  # Skip DB writes if no session (legacy mode)
        try:
            async with get_session() as session:
                from sqlalchemy import select, and_
                stmt = select(PositionModel).where(
                    and_(
                        PositionModel.session_id == self._session_id,
                        PositionModel.symbol == symbol,
                    )
                )
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()

                current_price = self._prices.get(symbol, pos["avg_entry_price"])
                unrealized = pos["quantity"] * (current_price - pos["avg_entry_price"])

                if existing:
                    existing.quantity = pos["quantity"]
                    existing.avg_entry_price = pos["avg_entry_price"]
                    existing.current_price = current_price
                    existing.unrealized_pnl = unrealized
                else:
                    db_pos = PositionModel(
                        session_id=self._session_id,
                        symbol=symbol,
                        exchange=pos.get("exchange", ""),
                        quantity=pos["quantity"],
                        avg_entry_price=pos["avg_entry_price"],
                        current_price=current_price,
                        unrealized_pnl=unrealized,
                    )
                    session.add(db_pos)
        except Exception:
            logger.exception("Failed to persist position %s", symbol)
