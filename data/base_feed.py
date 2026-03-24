"""Abstract base class for all data feeds."""

from abc import ABC, abstractmethod


class BaseFeed(ABC):
    """Interface that all exchange data feeds must implement."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the exchange."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully close the connection."""
        ...

    @abstractmethod
    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to market data for the given symbols."""
        ...
