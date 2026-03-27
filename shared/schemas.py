"""Pydantic v2 models for all inter-service messages, plus shared dataclasses.

Every message that goes through Redis is serializable via .model_dump_json()
and deserializable via .model_validate_json().
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from shared.enums import Exchange, OrderStatus, OrderType, SessionType, Side, Signal


# ---------------------------------------------------------------------------
# Shared dataclasses (used across strategy validators)
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Result of AST-based code validation (strategies, custom data funcs)."""

    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str):
        self.valid = False
        self.errors.append(msg)

    def add_warning(self, msg: str):
        self.warnings.append(msg)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MarketTick(BaseModel):
    """A single trade / price update from an exchange."""

    symbol: str
    price: float = Field(gt=0)
    volume: float = Field(ge=0)
    timestamp: datetime = Field(default_factory=_utcnow)
    exchange: Exchange
    session_id: str = ""
    source: str = "data"


class OHLCVBar(BaseModel):
    """Completed OHLCV candlestick bar."""

    symbol: str
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)
    interval: str  # e.g. "1m", "5m", "1h"
    timestamp: datetime = Field(default_factory=_utcnow)
    exchange: Exchange
    session_id: str = ""
    source: str = "data"


class TradeSignal(BaseModel):
    """Signal emitted by a strategy."""

    symbol: str
    signal: Signal
    strength: float = Field(ge=0.0, le=1.0)
    strategy_id: str
    timestamp: datetime = Field(default_factory=_utcnow)
    metadata: dict = Field(default_factory=dict)
    session_id: str = ""
    source: str = "strategy"


class OrderRequest(BaseModel):
    """Request to place an order, emitted by the risk manager."""

    symbol: str
    side: Side
    quantity: float = Field(gt=0)
    order_type: OrderType = OrderType.MARKET
    price: Optional[float] = None
    exchange: Exchange
    strategy_id: str
    timestamp: datetime = Field(default_factory=_utcnow)
    session_id: str = ""
    source: str = "risk"
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_limit_price(self) -> "OrderRequest":
        if self.order_type == OrderType.LIMIT and (self.price is None or self.price <= 0):
            raise ValueError("LIMIT orders require a positive price")
        return self


class OrderUpdate(BaseModel):
    """Update on an order's status."""

    order_id: str
    external_id: Optional[str] = None
    symbol: str
    side: Side
    status: OrderStatus
    filled_qty: float = Field(default=0.0, ge=0)
    avg_price: float = Field(default=0.0, ge=0)
    timestamp: datetime = Field(default_factory=_utcnow)
    exchange: Exchange
    session_id: str = ""
    source: str = "execution"


class RiskCheckResult(BaseModel):
    """Result of running a trade signal through the risk pipeline."""

    approved: bool
    reason: str = ""
    original_signal: TradeSignal


class AlertMessage(BaseModel):
    """Alert sent to the monitoring channel."""

    level: str = "info"  # info, warning, error, critical
    message: str
    source: str
    timestamp: datetime = Field(default_factory=_utcnow)
    session_id: str = ""
    metadata: dict = Field(default_factory=dict)


class LogEntry(BaseModel):
    """Structured log entry for the Logs page.

    Published to session:{id}:logs Redis channel by all pipeline components.
    Stored in-memory ring buffer on the web server, streamed to browser via SSE.
    """

    event_type: Literal[
        "data_scrape", "liquidation_order", "order_failed", "order_fill",
        "order_placed", "order_submit", "risk_approve", "risk_reject",
        "schedule_event", "session_event", "strategy_error", "strategy_eval",
    ]
    session_id: str = ""
    symbol: str = ""
    message: str = ""
    level: str = "info"  # info, warning, error
    source: str = ""     # strategy, risk, execution, session, data
    metadata: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utcnow)
