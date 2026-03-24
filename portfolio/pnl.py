"""P&L calculation — realized, unrealized, daily, and aggregate metrics."""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class PnLCalculator:
    """Computes various P&L metrics from position and trade data."""

    def __init__(self):
        self._realized_pnl: float = 0.0
        self._trades: list[dict] = []  # History of closed trades for metrics

    def record_close(
        self,
        symbol: str,
        quantity: float,
        entry_price: float,
        exit_price: float,
        side: str,
    ) -> float:
        """Record a position close and return realized P&L for this trade."""
        if side == "sell":
            pnl = quantity * (exit_price - entry_price)
        else:
            pnl = quantity * (entry_price - exit_price)

        self._realized_pnl += pnl
        self._trades.append({
            "symbol": symbol,
            "quantity": quantity,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": pnl,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return pnl

    @staticmethod
    def unrealized_pnl(
        quantity: float,
        avg_entry_price: float,
        current_price: float,
    ) -> float:
        """Compute unrealized P&L for a single position."""
        return quantity * (current_price - avg_entry_price)

    def total_realized(self) -> float:
        return self._realized_pnl

    def daily_pnl(self, current_equity: float, day_start_equity: float) -> float:
        return current_equity - day_start_equity

    def win_rate(self) -> float:
        if not self._trades:
            return 0.0
        wins = sum(1 for t in self._trades if t["pnl"] > 0)
        return wins / len(self._trades)

    def avg_win(self) -> float:
        wins = [t["pnl"] for t in self._trades if t["pnl"] > 0]
        return sum(wins) / len(wins) if wins else 0.0

    def avg_loss(self) -> float:
        losses = [t["pnl"] for t in self._trades if t["pnl"] < 0]
        return sum(losses) / len(losses) if losses else 0.0

    def get_summary(self, current_equity: float, day_start_equity: float) -> dict:
        """Return a full P&L summary dict."""
        return {
            "realized_pnl": self._realized_pnl,
            "daily_pnl": self.daily_pnl(current_equity, day_start_equity),
            "total_trades": len(self._trades),
            "win_rate": self.win_rate(),
            "avg_win": self.avg_win(),
            "avg_loss": self.avg_loss(),
        }
