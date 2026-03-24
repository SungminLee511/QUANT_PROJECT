"""Order router — consumes OrderRequests, routes to exchange adapters, tracks fills."""

import asyncio
import logging
import uuid

from db.session import get_session
from db.models import Order as OrderModel
from execution.alpaca_adapter import AlpacaAdapter
from execution.binance_adapter import BinanceAdapter
from execution.order import OrderState
from shared.enums import Exchange, OrderStatus
from shared.redis_client import RedisClient
from shared.schemas import OrderRequest, OrderUpdate

logger = logging.getLogger(__name__)


class OrderRouter:
    """Routes orders to the correct exchange and tracks their lifecycle."""

    def __init__(self, config: dict, redis: RedisClient):
        self._config = config
        self._redis = redis
        self._binance: BinanceAdapter | None = None
        self._alpaca: AlpacaAdapter | None = None
        self._open_orders: dict[str, OrderState] = {}
        self._running = False

        channels = config.get("redis", {}).get("channels", {})
        self._order_channel = channels.get("orders", "execution:orders")
        self._update_channel = channels.get("order_updates", "execution:updates")

    async def start(self) -> None:
        """Connect adapters, subscribe to orders, start polling."""
        # Initialize adapters
        if self._config.get("binance", {}).get("api_key"):
            self._binance = BinanceAdapter(self._config)
            await self._binance.connect()

        if self._config.get("alpaca", {}).get("api_key"):
            self._alpaca = AlpacaAdapter(self._config)
            await self._alpaca.connect()

        self._running = True

        # Subscribe to order requests
        await self._redis.subscribe(self._order_channel, self._on_order_request)

        # Start order status polling loop
        asyncio.create_task(self._poll_open_orders())

        logger.info("Order router started")

        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        self._running = False
        if self._binance:
            await self._binance.disconnect()
        if self._alpaca:
            await self._alpaca.disconnect()
        logger.info("Order router stopped")

    async def _on_order_request(self, data: dict) -> None:
        """Handle an incoming OrderRequest."""
        try:
            request = OrderRequest.model_validate(data)
            order_id = str(uuid.uuid4())

            # Create local order state
            order = OrderState(
                order_id=order_id,
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                order_type=request.order_type,
                exchange=request.exchange,
                strategy_id=request.strategy_id,
            )

            # Route to the correct adapter
            adapter = self._get_adapter(request.exchange)
            if adapter is None:
                logger.error("No adapter for exchange %s", request.exchange.value)
                order.transition(OrderStatus.FAILED)
                return

            # Place order
            try:
                external_id = await adapter.place_order(request)
                order.external_id = external_id
                order.transition(OrderStatus.PLACED)
            except Exception:
                logger.exception("Failed to place order %s", order_id)
                order.transition(OrderStatus.FAILED)
                return

            # Track and persist
            self._open_orders[order_id] = order
            await self._persist_order(order)

            # Publish initial update
            update = OrderUpdate(
                order_id=order_id,
                external_id=external_id,
                symbol=request.symbol,
                side=request.side,
                status=order.status,
                exchange=request.exchange,
            )
            await self._redis.publish(self._update_channel, update)

        except Exception:
            logger.exception("Error processing order request")

    def _get_adapter(self, exchange: Exchange):
        if exchange == Exchange.BINANCE:
            return self._binance
        elif exchange == Exchange.ALPACA:
            return self._alpaca
        return None

    async def _poll_open_orders(self) -> None:
        """Periodically poll open orders for status updates (safety net)."""
        while self._running:
            await asyncio.sleep(10)

            for order_id, order in list(self._open_orders.items()):
                if order.is_terminal:
                    self._open_orders.pop(order_id, None)
                    continue

                try:
                    adapter = self._get_adapter(order.exchange)
                    if adapter is None:
                        continue

                    if order.exchange == Exchange.BINANCE and hasattr(adapter, "get_order_status_for_symbol"):
                        update = await adapter.get_order_status_for_symbol(
                            order.symbol, order.external_id
                        )
                    else:
                        update = await adapter.get_order_status(order.external_id)

                    # Update local state if changed
                    if update.status != order.status:
                        order.transition(update.status)
                        order.filled_quantity = update.filled_qty
                        order.avg_price = update.avg_price

                        update.order_id = order_id
                        await self._redis.publish(self._update_channel, update)
                        await self._persist_order(order)

                        logger.info(
                            "Order %s updated: %s (filled=%.4f @ %.2f)",
                            order_id,
                            order.status.value,
                            order.filled_quantity,
                            order.avg_price,
                        )

                except Exception:
                    logger.exception("Error polling order %s", order_id)

    async def _persist_order(self, order: OrderState) -> None:
        """Persist order state to the database."""
        try:
            async with get_session() as session:
                # Upsert: check if order exists
                from sqlalchemy import select
                stmt = select(OrderModel).where(
                    OrderModel.external_id == order.external_id
                )
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    existing.status = order.status.value
                    existing.filled_quantity = order.filled_quantity
                    existing.updated_at = order.updated_at
                else:
                    db_order = OrderModel(
                        external_id=order.external_id or order.order_id,
                        symbol=order.symbol,
                        side=order.side.value,
                        quantity=order.quantity,
                        filled_quantity=order.filled_quantity,
                        order_type=order.order_type.value,
                        status=order.status.value,
                        exchange=order.exchange.value,
                        strategy_id=order.strategy_id,
                    )
                    session.add(db_order)
        except Exception:
            logger.exception("Failed to persist order %s", order.order_id)
