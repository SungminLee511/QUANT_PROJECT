"""Abstract exchange adapter interface."""

from abc import ABC, abstractmethod

from shared.schemas import OrderRequest, OrderUpdate


class BaseExchangeAdapter(ABC):
    """Interface that all exchange adapters must implement."""

    @abstractmethod
    async def place_order(self, order_request: OrderRequest) -> str:
        """Place an order. Returns external order ID."""
        ...

    @abstractmethod
    async def cancel_order(self, external_order_id: str) -> bool:
        """Cancel an open order. Returns True if successful."""
        ...

    @abstractmethod
    async def get_order_status(self, external_order_id: str) -> OrderUpdate:
        """Get current status of an order."""
        ...

    @abstractmethod
    async def get_balances(self) -> dict:
        """Get account balances."""
        ...

    @abstractmethod
    async def get_positions(self) -> list:
        """Get open positions."""
        ...
