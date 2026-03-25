"""Shared enums used across all services."""

from enum import Enum


class Exchange(str, Enum):
    BINANCE = "binance"
    ALPACA = "alpaca"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class Signal(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class OrderStatus(str, Enum):
    PENDING = "pending"
    PLACED = "placed"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"


class AssetType(str, Enum):
    CRYPTO = "crypto"
    EQUITY = "equity"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class DataResolution(str, Enum):
    """Time-based data scrape intervals."""
    MIN_1 = "1min"
    MIN_5 = "5min"
    MIN_15 = "15min"
    MIN_30 = "30min"
    MIN_60 = "60min"
    DAY_1 = "1day"

    @property
    def seconds(self) -> int:
        """Return interval in seconds."""
        return {
            "1min": 60, "5min": 300, "15min": 900,
            "30min": 1800, "60min": 3600, "1day": 86400,
        }[self.value]


class SessionType(str, Enum):
    BINANCE = "binance"
    ALPACA = "alpaca"
    BINANCE_SIM = "binance_sim"
    ALPACA_SIM = "alpaca_sim"

    @property
    def is_simulation(self) -> bool:
        return self in (SessionType.BINANCE_SIM, SessionType.ALPACA_SIM)

    @property
    def exchange(self) -> "Exchange":
        if self in (SessionType.BINANCE, SessionType.BINANCE_SIM):
            return Exchange.BINANCE
        return Exchange.ALPACA
