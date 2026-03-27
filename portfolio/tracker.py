"""Central position and balance tracker — consumes order updates, maintains state."""

import asyncio
import logging
from datetime import datetime, timezone

from db.models import Position as PositionModel, EquitySnapshot
from db.session import get_session
from portfolio.pnl import PnLCalculator
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
        self._stale_price_warned: set[str] = set()  # Symbols warned about stale price
        self._position_lock = asyncio.Lock()  # Guards position + cash mutations
        # Track cumulative filled qty per order to compute deltas (BUG-16)
        self._last_filled: dict[str, float] = {}  # order_id -> last seen filled_qty
        # P&L tracking (BUG-27)
        self._pnl = PnLCalculator()

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
        """Update positions based on order fill updates.

        filled_qty from exchanges is cumulative (e.g., partial fill #1: 5,
        partial fill #2: 8 means 3 new). We track the last-seen filled_qty
        per order_id and only apply the delta (BUG-16 fix).
        """
        try:
            update = OrderUpdate.model_validate(data)

            if update.status not in (OrderStatus.FILLED, OrderStatus.PARTIAL):
                return
            if update.filled_qty <= 0 or update.avg_price <= 0:
                return

            # Compute incremental fill qty (cumulative → delta)
            # FAUDIT-1: Use sentinel -1.0 instead of pop() for completed orders.
            # If we pop, a duplicate FILLED message sees prev_filled=0.0 and
            # re-applies the entire fill amount, doubling the position.
            prev_filled = self._last_filled.get(update.order_id, 0.0)
            if prev_filled < 0:
                return  # Already fully processed — duplicate FILLED message
            delta_qty = update.filled_qty - prev_filled
            self._last_filled[update.order_id] = update.filled_qty

            # Mark completed orders with sentinel (cleaned up periodically)
            if update.status == OrderStatus.FILLED:
                self._last_filled[update.order_id] = -1.0

            if delta_qty <= 0:
                return  # No new fill (duplicate or stale update)

            async with self._position_lock:
                await self._apply_fill(update, delta_qty)

        except Exception:
            logger.exception("Error processing order update")

    async def _apply_fill(self, update: OrderUpdate, delta_qty: float) -> None:
        """Apply a fill delta to position state (must hold _position_lock)."""
        symbol = update.symbol
        pos = self._positions.get(symbol, {
            "quantity": 0.0,
            "avg_entry_price": 0.0,
            "exchange": update.exchange.value,
        })

        if update.side == Side.BUY:
            current_qty = pos["quantity"]
            self._cash -= delta_qty * update.avg_price

            if current_qty < -0.0001:
                # We have a short position — buy covers some/all of it
                cover_qty = min(delta_qty, abs(current_qty))
                entry_price = pos["avg_entry_price"]
                if entry_price > 0 and cover_qty > 0:
                    pnl = self._pnl.record_close(
                        symbol=symbol,
                        quantity=cover_qty,
                        entry_price=entry_price,
                        exit_price=update.avg_price,
                        side="buy",
                    )
                    logger.info(
                        "Realized P&L (short cover): %s qty=%.4f entry=%.2f exit=%.2f pnl=%.2f (session=%s)",
                        symbol, cover_qty, entry_price, update.avg_price, pnl, self._session_id,
                    )
                remainder = delta_qty - cover_qty
                if remainder > 0.0001:
                    pos["quantity"] = remainder
                    pos["avg_entry_price"] = update.avg_price
                else:
                    pos["quantity"] = current_qty + delta_qty
                    if abs(pos["quantity"]) <= 0.0001:
                        pos["quantity"] = 0.0
                        pos["avg_entry_price"] = 0.0
            else:
                # No short — accumulate long position
                old_value = current_qty * pos["avg_entry_price"]
                new_value = delta_qty * update.avg_price
                new_qty = current_qty + delta_qty
                pos["avg_entry_price"] = (old_value + new_value) / new_qty if new_qty > 0 else 0
                pos["quantity"] = new_qty

        elif update.side == Side.SELL:
            current_qty = pos["quantity"]
            self._cash += delta_qty * update.avg_price

            if current_qty > 0.0001:
                close_qty = min(delta_qty, current_qty)
                entry_price = pos["avg_entry_price"]
                if entry_price > 0 and close_qty > 0:
                    pnl = self._pnl.record_close(
                        symbol=symbol,
                        quantity=close_qty,
                        entry_price=entry_price,
                        exit_price=update.avg_price,
                        side="sell",
                    )
                    logger.info(
                        "Realized P&L: %s qty=%.4f entry=%.2f exit=%.2f pnl=%.2f (session=%s)",
                        symbol, close_qty, entry_price, update.avg_price, pnl, self._session_id,
                    )
                remainder = delta_qty - close_qty
                if remainder > 0.0001:
                    pos["quantity"] = -(remainder)
                    pos["avg_entry_price"] = update.avg_price
                else:
                    pos["quantity"] = current_qty - delta_qty
                    if abs(pos["quantity"]) <= 0.0001:
                        pos["quantity"] = 0.0
                        pos["avg_entry_price"] = 0.0
            else:
                # No long — accumulate short position
                old_value = abs(current_qty) * pos["avg_entry_price"]
                new_value = delta_qty * update.avg_price
                new_qty = abs(current_qty) + delta_qty
                pos["avg_entry_price"] = (old_value + new_value) / new_qty if new_qty > 0 else 0
                pos["quantity"] = current_qty - delta_qty

        self._positions[symbol] = pos
        self._prices[symbol] = update.avg_price

        await self._persist_position(symbol, pos)

        logger.info(
            "Position updated: %s qty=%.4f avg_price=%.2f delta=%.4f (session=%s)",
            symbol, pos["quantity"], pos["avg_entry_price"], delta_qty, self._session_id,
        )

    async def _on_market_data(self, data: dict) -> None:
        """Update latest prices from market data."""
        try:
            symbol = data.get("symbol")
            price = data.get("price") or data.get("close")
            if symbol and price:
                self._prices[symbol] = float(price)
        except Exception:
            logger.debug("Failed to parse market data update", exc_info=True)

    def _get_price(self, symbol: str, fallback: float) -> float:
        """Get current price, falling back to entry price with one-time warning."""
        price = self._prices.get(symbol)
        if price is not None:
            self._stale_price_warned.discard(symbol)
            return price
        if symbol not in self._stale_price_warned:
            logger.warning(
                "No market price for %s — using entry price %.4f as fallback (session=%s)",
                symbol, fallback, self._session_id,
            )
            self._stale_price_warned.add(symbol)
        return fallback

    def get_total_equity(self) -> float:
        """Cash + sum of all position values at current prices.

        Includes both long (positive qty) and short (negative qty) positions.
        Short positions contribute negative value to equity.
        """
        positions_value = sum(
            pos["quantity"] * self._get_price(symbol, pos["avg_entry_price"])
            for symbol, pos in self._positions.items()
            if abs(pos["quantity"]) > 0.0001
        )
        return self._cash + positions_value

    def get_positions_value(self) -> float:
        return sum(
            pos["quantity"] * self._get_price(symbol, pos["avg_entry_price"])
            for symbol, pos in self._positions.items()
            if abs(pos["quantity"]) > 0.0001
        )

    def get_all_positions(self) -> dict:
        return {
            symbol: {
                **pos,
                "current_price": self._get_price(symbol, pos["avg_entry_price"]),
                "unrealized_pnl": pos["quantity"] * (
                    self._get_price(symbol, pos["avg_entry_price"]) - pos["avg_entry_price"]
                ),
            }
            for symbol, pos in self._positions.items()
            if abs(pos["quantity"]) > 0.0001
        }

    async def _publish_state_loop(self) -> None:
        """Publish portfolio state to Redis every 5 seconds for other services."""
        while self._running:
            try:
                equity = self.get_total_equity()
                self._peak_equity = max(self._peak_equity, equity)

                pnl_summary = self._pnl.get_summary(equity, self._day_start_equity)

                state = {
                    "total_equity": equity,
                    "peak_equity": self._peak_equity,
                    "day_start_equity": self._day_start_equity,
                    "daily_pnl": equity - self._day_start_equity,
                    "cash": self._cash,
                    "realized_pnl": pnl_summary["realized_pnl"],
                    "total_closed_trades": pnl_summary["total_trades"],
                    "win_rate": pnl_summary["win_rate"],
                    "open_positions": sum(
                        1 for p in self._positions.values() if abs(p["quantity"]) > 0.0001
                    ),
                    "positions": [
                        {
                            "symbol": s,
                            "quantity": p["quantity"],
                            "avg_entry_price": p["avg_entry_price"],
                            "current_price": self._prices.get(s, 0.0),
                            "unrealized_pnl": p["quantity"] * (self._prices.get(s, p["avg_entry_price"]) - p["avg_entry_price"]),
                        }
                        for s, p in self._positions.items()
                        if abs(p["quantity"]) > 0.0001
                    ],
                    "position_symbols": [
                        s for s, p in self._positions.items() if abs(p["quantity"]) > 0.0001
                    ],
                    "prices": self._prices,
                }
                await self._redis.set_flag(self._state_key, state)
            except Exception:
                logger.exception("Error publishing portfolio state")
            await asyncio.sleep(5)

    async def _snapshot_loop(self) -> None:
        """Store equity snapshots to DB every 60 seconds + reconcile positions."""
        interval = self._config.get("portfolio", {}).get("reconcile_interval_sec", 60)
        reconcile_counter = 0
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

            # FAUDIT-1: Prune completed-order sentinels to prevent memory leak
            completed = [k for k, v in self._last_filled.items() if v < 0]
            for k in completed:
                del self._last_filled[k]

            # ARCH-8: Reconcile in-memory vs DB positions every 5 snapshots (~5 min)
            reconcile_counter += 1
            if reconcile_counter >= 5:
                reconcile_counter = 0
                await self._reconcile_positions()

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

                current_price = self._get_price(symbol, pos["avg_entry_price"])
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

    async def _reconcile_positions(self) -> None:
        """ARCH-8: Compare in-memory positions with DB positions and log drift.

        Runs periodically to detect divergence between the in-memory tracker
        (source of truth for speed) and DB (source of truth for durability).
        Does NOT auto-correct — only warns so an operator can investigate.
        """
        if not self._session_id:
            return
        try:
            from sqlalchemy import select

            async with get_session() as session:
                stmt = select(PositionModel).where(
                    PositionModel.session_id == self._session_id
                )
                result = await session.execute(stmt)
                db_positions = {row.symbol: row for row in result.scalars().all()}

            # Compare each in-memory position with DB
            mem_symbols = {
                s for s, p in self._positions.items() if abs(p["quantity"]) > 0.0001
            }
            db_symbols = {
                s for s, row in db_positions.items() if abs(row.quantity) > 0.0001
            }

            # Check for symbol mismatches
            mem_only = mem_symbols - db_symbols
            db_only = db_symbols - mem_symbols
            if mem_only:
                logger.warning(
                    "RECONCILE: positions in memory but not DB: %s (session=%s)",
                    mem_only, self._session_id,
                )
            if db_only:
                logger.warning(
                    "RECONCILE: positions in DB but not memory: %s (session=%s)",
                    db_only, self._session_id,
                )

            # Check quantity drift on shared symbols
            for sym in mem_symbols & db_symbols:
                mem_qty = self._positions[sym]["quantity"]
                db_qty = db_positions[sym].quantity
                if db_qty == 0:
                    continue
                drift_pct = abs(mem_qty - db_qty) / abs(db_qty) * 100
                if drift_pct > 1.0:  # >1% drift
                    logger.warning(
                        "RECONCILE: %s quantity drift %.2f%% — memory=%.6f vs DB=%.6f (session=%s)",
                        sym, drift_pct, mem_qty, db_qty, self._session_id,
                    )
        except Exception:
            logger.debug(
                "Reconciliation check failed (session=%s)", self._session_id,
                exc_info=True,
            )
