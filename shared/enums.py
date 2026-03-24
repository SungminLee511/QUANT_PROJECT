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
