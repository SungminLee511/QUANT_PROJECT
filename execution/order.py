"""Order model and state machine with valid transitions."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from shared.enums import Exchange, OrderStatus, OrderType, Side

logger = logging.getLogger(__name__)

# Valid state transitions
_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.PLACED, OrderStatus.REJECTED, OrderStatus.FAILED},
    OrderStatus.PLACED: {OrderStatus.PARTIAL, OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.FAILED},
    OrderStatus.PARTIAL: {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.FAILED},
    OrderStatus.FILLED: set(),       # Terminal state
    OrderStatus.CANCELLED: set(),    # Terminal state
    OrderStatus.REJECTED: set(),     # Terminal state
    OrderStatus.FAILED: set(),       # Terminal state
}


class InvalidTransitionError(Exception):
    pass


@dataclass
class OrderState:
    """In-memory order tracking with state machine enforcement."""

    order_id: str
    external_id: Optional[str] = None
    symbol: str = ""
    side: Side = Side.BUY
    quantity: float = 0.0
    filled_quantity: float = 0.0
    avg_price: float = 0.0
    order_type: OrderType = OrderType.MARKET
    status: OrderStatus = OrderStatus.PENDING
    exchange: Exchange = Exchange.BINANCE
    strategy_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def transition(self, new_status: OrderStatus) -> None:
        """Transition to a new status, enforcing valid transitions."""
        valid = _TRANSITIONS.get(self.status, set())
        if new_status not in valid:
            raise InvalidTransitionError(
                f"Cannot transition order {self.order_id} from {self.status.value} to {new_status.value}. "
                f"Valid transitions: {[s.value for s in valid]}"
            )
        old = self.status
        self.status = new_status
        self.updated_at = datetime.now(timezone.utc)
        logger.debug(
            "Order %s: %s -> %s", self.order_id, old.value, new_status.value
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.FAILED,
        )
