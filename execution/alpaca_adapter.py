"""Alpaca exchange adapter — order placement, tracking, balance queries.

All TradingClient calls are wrapped in asyncio.to_thread() because the
Alpaca SDK is synchronous. Without this, every HTTP call blocks the
entire event loop for 100-500ms (BUG-21 fix).
"""

import asyncio
import logging

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderType as AlpacaOrderType, TimeInForce
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest

from execution.base_adapter import BaseExchangeAdapter
from shared.enums import Exchange, OrderStatus, Side
from shared.schemas import OrderRequest, OrderUpdate

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
BASE_DELAY = 2


class AlpacaAdapter(BaseExchangeAdapter):
    def __init__(self, config: dict):
        alpaca_cfg = config.get("alpaca", {})
        self._api_key = alpaca_cfg.get("api_key", "")
        self._api_secret = alpaca_cfg.get("api_secret", "")
        self._paper = alpaca_cfg.get("paper", True)
        self._client: TradingClient | None = None

    async def connect(self) -> None:
        self._client = TradingClient(
            api_key=self._api_key,
            secret_key=self._api_secret,
            paper=self._paper,
        )
        logger.info("Alpaca adapter connected (paper=%s)", self._paper)

    async def disconnect(self) -> None:
        self._client = None

    async def place_order(self, order_request: OrderRequest) -> str:
        """Place an order on Alpaca with retry logic."""
        side = OrderSide.BUY if order_request.side == Side.BUY else OrderSide.SELL

        if order_request.order_type.value == "limit" and order_request.price:
            req = LimitOrderRequest(
                symbol=order_request.symbol,
                qty=order_request.quantity,
                side=side,
                time_in_force=TimeInForce.DAY,
                limit_price=order_request.price,
            )
        else:
            req = MarketOrderRequest(
                symbol=order_request.symbol,
                qty=order_request.quantity,
                side=side,
                time_in_force=TimeInForce.DAY,
            )

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                order = await asyncio.to_thread(self._client.submit_order, req)
                external_id = str(order.id)
                logger.info(
                    "Alpaca order placed: %s %s qty=%s -> id=%s",
                    order_request.side.value,
                    order_request.symbol,
                    order_request.quantity,
                    external_id,
                )
                return external_id
            except Exception as e:
                logger.warning(
                    "Alpaca order error (attempt %d/%d): %s",
                    attempt, MAX_RETRIES, e,
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(BASE_DELAY * (2 ** (attempt - 1)))
                    continue
                raise

        raise RuntimeError("Exhausted retries placing Alpaca order")

    async def cancel_order(self, external_order_id: str) -> bool:
        try:
            await asyncio.to_thread(self._client.cancel_order_by_id, external_order_id)
            return True
        except Exception:
            logger.exception("Failed to cancel Alpaca order %s", external_order_id)
            return False

    async def get_order_status(self, external_order_id: str) -> OrderUpdate:
        order = await asyncio.to_thread(self._client.get_order_by_id, external_order_id)

        status_map = {
            "new": OrderStatus.PLACED,
            "accepted": OrderStatus.PLACED,
            "partially_filled": OrderStatus.PARTIAL,
            "filled": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELLED,
            "expired": OrderStatus.CANCELLED,
            "rejected": OrderStatus.REJECTED,
            "pending_new": OrderStatus.PENDING,
        }

        filled_qty = float(order.filled_qty) if order.filled_qty else 0.0
        avg_price = float(order.filled_avg_price) if order.filled_avg_price else 0.0
        # Only report avg_price when there's actually a fill
        if filled_qty <= 0:
            avg_price = 0.0

        return OrderUpdate(
            order_id=external_order_id,
            external_id=external_order_id,
            symbol=order.symbol,
            side=Side.BUY if str(order.side) == "buy" else Side.SELL,
            status=status_map.get(str(order.status), OrderStatus.PENDING),
            filled_qty=filled_qty,
            avg_price=avg_price,
            exchange=Exchange.ALPACA,
        )

    async def get_balances(self) -> dict:
        account = await asyncio.to_thread(self._client.get_account)
        return {
            "USD": {
                "free": float(account.cash),
                "total": float(account.equity),
                "buying_power": float(account.buying_power),
            }
        }

    async def get_positions(self) -> list:
        positions = await asyncio.to_thread(self._client.get_all_positions)
        return [
            {
                "symbol": p.symbol,
                "quantity": float(p.qty),
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "unrealized_pnl": float(p.unrealized_pl),
            }
            for p in positions
        ]
