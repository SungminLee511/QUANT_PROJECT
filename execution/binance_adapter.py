"""Binance exchange adapter — order placement, tracking, balance queries."""

import asyncio
import logging
import uuid

from binance import AsyncClient
from binance.exceptions import BinanceAPIException

from execution.base_adapter import BaseExchangeAdapter
from shared.enums import Exchange, OrderStatus, Side
from shared.schemas import OrderRequest, OrderUpdate

logger = logging.getLogger(__name__)

# Retry config
MAX_RETRIES = 5
BASE_DELAY = 2  # seconds


class BinanceAdapter(BaseExchangeAdapter):
    def __init__(self, config: dict):
        binance_cfg = config.get("binance", {})
        self._api_key = binance_cfg.get("api_key", "")
        self._api_secret = binance_cfg.get("api_secret", "")
        self._testnet = binance_cfg.get("testnet", True)
        self._client: AsyncClient | None = None
        # Map external_order_id -> symbol for cancel/status lookups (BUG-20)
        self._order_symbols: dict[str, str] = {}

    async def connect(self) -> None:
        self._client = await AsyncClient.create(
            api_key=self._api_key,
            api_secret=self._api_secret,
            testnet=self._testnet,
        )
        logger.info("Binance adapter connected (testnet=%s)", self._testnet)

    async def disconnect(self) -> None:
        if self._client:
            await self._client.close_connection()

    async def place_order(self, order_request: OrderRequest) -> str:
        """Place an order on Binance with retry logic."""
        params = {
            "symbol": order_request.symbol,
            "side": order_request.side.value.upper(),
            "type": order_request.order_type.value.upper(),
            "quantity": str(order_request.quantity),
        }
        if order_request.price is not None and order_request.order_type.value == "limit":
            params["price"] = str(order_request.price)
            params["timeInForce"] = "GTC"

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = await self._client.create_order(**params)
                external_id = str(result.get("orderId", ""))
                self._order_symbols[external_id] = order_request.symbol
                logger.info(
                    "Binance order placed: %s %s %s qty=%s -> id=%s",
                    order_request.side.value,
                    order_request.symbol,
                    order_request.order_type.value,
                    order_request.quantity,
                    external_id,
                )
                return external_id
            except BinanceAPIException as e:
                if e.status_code and e.status_code >= 500:
                    logger.warning(
                        "Binance server error (attempt %d/%d): %s",
                        attempt, MAX_RETRIES, e,
                    )
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(BASE_DELAY * (2 ** (attempt - 1)))
                        continue
                # Client error or exhausted retries
                logger.error("Binance order failed: %s", e)
                raise
            except Exception as e:
                logger.warning(
                    "Binance transient error (attempt %d/%d): %s",
                    attempt, MAX_RETRIES, e,
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(BASE_DELAY * (2 ** (attempt - 1)))
                    continue
                raise

        raise RuntimeError("Exhausted retries placing Binance order")

    async def cancel_order(self, external_order_id: str, symbol: str | None = None) -> bool:
        """Cancel a Binance order. Looks up symbol from internal map if not provided."""
        try:
            sym = symbol or self._order_symbols.get(external_order_id)
            if not sym:
                raise ValueError(
                    f"Cannot cancel Binance order {external_order_id} — symbol unknown "
                    f"(adapter may have restarted, losing order-symbol map)"
                )
            await self._client.cancel_order(symbol=sym, orderId=int(external_order_id))
            self._order_symbols.pop(external_order_id, None)
            return True
        except Exception:
            logger.exception("Failed to cancel Binance order %s", external_order_id)
            return False

    async def get_order_status(self, external_order_id: str) -> OrderUpdate:
        # Note: Binance requires symbol — caller must handle this context
        raise NotImplementedError(
            "Use get_order_status_for_symbol() instead for Binance"
        )

    async def get_order_status_for_symbol(
        self, symbol: str, external_order_id: str
    ) -> OrderUpdate:
        """Get order status from Binance (requires symbol)."""
        result = await self._client.get_order(
            symbol=symbol, orderId=int(external_order_id)
        )
        status_map = {
            "NEW": OrderStatus.PLACED,
            "PARTIALLY_FILLED": OrderStatus.PARTIAL,
            "FILLED": OrderStatus.FILLED,
            "CANCELED": OrderStatus.CANCELLED,
            "REJECTED": OrderStatus.REJECTED,
            "EXPIRED": OrderStatus.CANCELLED,
        }
        return OrderUpdate(
            order_id=external_order_id,
            external_id=external_order_id,
            symbol=symbol,
            side=Side.BUY if result.get("side") == "BUY" else Side.SELL,
            status=status_map.get(result.get("status", ""), OrderStatus.PENDING),
            filled_qty=float(result.get("executedQty", 0)),
            avg_price=float(result.get("avgPrice", 0) or result.get("price", 0)),
            exchange=Exchange.BINANCE,
        )

    async def get_balances(self) -> dict:
        account = await self._client.get_account()
        balances = {}
        for b in account.get("balances", []):
            free = float(b.get("free", 0))
            locked = float(b.get("locked", 0))
            if free > 0 or locked > 0:
                balances[b["asset"]] = {"free": free, "locked": locked}
        return balances

    async def get_positions(self) -> list:
        # Binance spot doesn't have "positions" — return balances as positions
        balances = await self.get_balances()
        return [
            {"symbol": asset, "quantity": info["free"] + info["locked"]}
            for asset, info in balances.items()
            if info["free"] + info["locked"] > 0
        ]
