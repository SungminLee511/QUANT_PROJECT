"""Weight rebalancer — converts target portfolio weights to buy/sell orders."""

import logging
from datetime import datetime, timezone

import numpy as np

from shared.enums import Exchange, OrderType, Side
from shared.schemas import OrderRequest

logger = logging.getLogger(__name__)

# Minimum order value in base currency (e.g., $) to avoid dust orders
MIN_ORDER_VALUE = 1.0


class WeightRebalancer:
    """Converts normalized portfolio weights to rebalancing orders.

    Compares target weights against current positions and generates
    the minimal set of BUY/SELL orders to reach the target allocation.
    """

    def __init__(self, session_id: str, symbols: list[str], exchange: Exchange, strategy_id: str = "v2", strategy_mode: str = "rebalance"):
        self.session_id = session_id
        self.symbols = symbols
        self.exchange = exchange
        self.strategy_id = strategy_id
        self.strategy_mode = strategy_mode

    def rebalance(
        self,
        target_weights: np.ndarray,
        current_positions: dict[str, float],
        total_equity: float,
        current_prices: np.ndarray,
    ) -> list[OrderRequest]:
        """Generate orders to move from current positions to target weights.

        Args:
            target_weights: [N] normalized weights (sum |w| = 1).
                            Positive = long, negative = short.
            current_positions: dict[symbol -> quantity].
                               Positive qty = long, negative = short.
            total_equity: Total portfolio value (cash + positions).
            current_prices: [N] current price per symbol.

        Returns:
            List of OrderRequest to execute.
        """
        orders = []
        n = len(self.symbols)

        if target_weights.shape != (n,) or current_prices.shape != (n,):
            logger.error(
                "Session %s: shape mismatch — weights %s, prices %s, symbols %d",
                self.session_id, target_weights.shape, current_prices.shape, n,
            )
            return orders

        if total_equity <= 0:
            logger.error(
                "Session %s: total_equity=%.4f is non-positive — skipping rebalance",
                self.session_id, total_equity,
            )
            return orders

        for i, symbol in enumerate(self.symbols):
            price = current_prices[i]
            if price <= 0:
                logger.warning(
                    "Session %s: skipping %s — price %.6f is non-positive",
                    self.session_id, symbol, price,
                )
                continue

            # Target value for this stock
            target_value = target_weights[i] * total_equity

            # Current value
            current_qty = current_positions.get(symbol, 0.0)
            current_value = current_qty * price

            # Difference
            diff_value = target_value - current_value

            # Skip dust orders
            if abs(diff_value) < MIN_ORDER_VALUE:
                continue

            qty = abs(diff_value) / price
            side = Side.BUY if diff_value > 0 else Side.SELL

            # For long-only mode: cap sell quantity to current position.
            # For long_short mode: allow selling beyond holdings (opens short).
            if side == Side.SELL and self.strategy_mode != "long_short":
                qty = min(qty, max(current_qty, 0.0))
                if qty * price < MIN_ORDER_VALUE:
                    continue

            order = OrderRequest(
                symbol=symbol,
                side=side,
                quantity=qty,
                order_type=OrderType.MARKET,
                exchange=self.exchange,
                strategy_id=self.strategy_id,
                session_id=self.session_id,
                metadata={
                    "target_weight": float(target_weights[i]),
                    "target_value": float(target_value),
                    "current_value": float(current_value),
                    "diff_value": float(diff_value),
                },
            )
            orders.append(order)

        if orders:
            logger.info(
                "Session %s: rebalancer generated %d orders (equity=%.2f)",
                self.session_id, len(orders), total_equity,
            )

        return orders
