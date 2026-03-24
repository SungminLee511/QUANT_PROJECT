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
