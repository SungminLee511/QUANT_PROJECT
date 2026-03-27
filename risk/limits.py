"""Individual risk limit checks. Each returns (approved: bool, reason: str).

V1 functions (check_position_size, check_max_positions) operate on TradeSignal.
V2 functions (check_portfolio_risk) operate on portfolio state only — no signal needed.
"""

import logging
from typing import Any

from shared.redis_client import RedisClient
from shared.schemas import TradeSignal

logger = logging.getLogger(__name__)


def check_position_size(
    signal: TradeSignal,
    portfolio_state: dict[str, Any],
    config: dict,
) -> tuple[bool, str]:
    """Reject if the signal would allocate more than max_position_pct of equity."""
    risk_cfg = config.get("risk", {})
    max_pct = risk_cfg.get("max_position_pct", 0.10)
    total_equity = portfolio_state.get("total_equity", 0)
    current_price = portfolio_state.get("prices", {}).get(signal.symbol, 0)

    if total_equity <= 0 or current_price <= 0:
        # BUG-30 fix: reject when equity/price unavailable instead of blindly allowing
        return False, "Cannot evaluate position size: equity or price unavailable"

    # FAUDIT-4: Check total position exposure (existing + proposed), not just the
    # proposed order.  The old check compared (strength * max_pct * equity) against
    # (max_pct * equity), which is always true since strength ∈ [0, 1].
    proposed_notional = signal.strength * max_pct * total_equity
    # Current position value for this symbol
    position_symbols = portfolio_state.get("position_symbols", set())
    existing_value = 0.0
    if signal.symbol in position_symbols:
        positions = portfolio_state.get("positions", [])
        for pos in positions:
            if pos.get("symbol") == signal.symbol:
                existing_value = abs(pos.get("quantity", 0) * current_price)
                break
    total_exposure = existing_value + proposed_notional
    max_allowed = total_equity * max_pct
    if total_exposure > max_allowed:
        return False, (
            f"Position exposure ${total_exposure:.0f} (existing ${existing_value:.0f} + "
            f"new ${proposed_notional:.0f}) would exceed "
            f"{max_pct*100:.0f}% of equity (${max_allowed:.0f})"
        )

    return True, ""


def check_max_positions(
    signal: TradeSignal,
    portfolio_state: dict[str, Any],
    config: dict,
) -> tuple[bool, str]:
    """Reject if opening a new position would exceed max_open_positions."""
    risk_cfg = config.get("risk", {})
    max_positions = risk_cfg.get("max_open_positions", 10)
    open_positions = portfolio_state.get("open_positions", 0)
    has_position = signal.symbol in portfolio_state.get("position_symbols", set())

    # If we already have this symbol, it's not a new position
    if has_position:
        return True, ""

    if signal.signal.value == "buy" and open_positions >= max_positions:
        return False, f"Max open positions ({max_positions}) reached"

    return True, ""


def check_drawdown(
    portfolio_state: dict[str, Any],
    config: dict,
) -> tuple[bool, str]:
    """Halt trading if peak-to-trough drawdown exceeds threshold."""
    risk_cfg = config.get("risk", {})
    max_dd = risk_cfg.get("max_drawdown_pct", 0.05)
    peak_equity = portfolio_state.get("peak_equity", 0)
    current_equity = portfolio_state.get("total_equity", 0)

    if peak_equity <= 0:
        return True, ""

    drawdown = (peak_equity - current_equity) / peak_equity
    if drawdown >= max_dd:
        return False, f"Drawdown {drawdown*100:.1f}% exceeds limit {max_dd*100:.0f}%"

    return True, ""


def check_daily_loss(
    portfolio_state: dict[str, Any],
    config: dict,
) -> tuple[bool, str]:
    """Halt trading if daily loss exceeds threshold.

    Note: daily_pnl = current_equity - day_start_equity, which includes
    both realized and unrealized P&L. This is intentional — the kill
    switch should fire on total portfolio drawdown, not just closed trades.
    Unrealized losses represent real risk exposure.
    """
    risk_cfg = config.get("risk", {})
    max_daily = risk_cfg.get("max_daily_loss_pct", 0.03)

    # 0 means disabled by user
    if not max_daily:
        return True, ""

    daily_pnl = portfolio_state.get("daily_pnl", 0)
    start_equity = portfolio_state.get("day_start_equity", 0)

    if start_equity <= 0:
        return True, ""

    loss_pct = abs(daily_pnl) / start_equity if daily_pnl < 0 else 0
    if loss_pct >= max_daily:
        return False, f"Daily loss {loss_pct*100:.1f}% exceeds limit {max_daily*100:.0f}%"

    return True, ""


async def check_kill_switch(redis: RedisClient, config: dict) -> tuple[bool, str]:
    """Reject all signals if kill switch is active."""
    key = config.get("risk", {}).get("kill_switch_key", "risk:kill_switch")
    state = await redis.get_flag(key)
    if state and state.get("active", False):
        reason = state.get("reason", "Kill switch active")
        return False, f"Kill switch: {reason}"
    return True, ""


# ── V2 Weight-Based Risk Checks ──────────────────────────────────────


def check_portfolio_risk(
    portfolio_state: dict[str, Any],
    config: dict,
) -> tuple[bool, str]:
    """Combined drawdown + daily loss check for V2 weight-based pipeline.

    Called after weight normalization, before order generation.
    If this fails, the session manager should activate the kill switch
    and flatten all positions (zero weights).

    Returns:
        (ok, reason) — ok=True means trading can proceed.
    """
    # Drawdown check
    ok, reason = check_drawdown(portfolio_state, config)
    if not ok:
        return False, reason

    # Daily loss check
    ok, reason = check_daily_loss(portfolio_state, config)
    if not ok:
        return False, reason

    return True, ""


# ── Short Position Risk Check ──────────────────────────────────────


def check_short_loss(
    positions: dict[str, float],
    current_prices: dict[str, float],
    entry_prices: dict[str, float],
    short_loss_limit_pct: float = 1.0,
) -> tuple[bool, str]:
    """Check if any short position has exceeded its loss limit.

    For each short position (negative qty), compute:
      unrealized_loss = |qty| * (current_price - entry_price)
      notional = |qty| * entry_price

    If unrealized_loss >= notional * short_loss_limit_pct → kill switch.

    Args:
        positions: symbol → qty (negative = short).
        current_prices: symbol → current price.
        entry_prices: symbol → price when short was opened.
        short_loss_limit_pct: loss threshold as fraction of notional (1.0 = 100%).

    Returns:
        (True, "") if OK, (False, reason) if kill switch should fire.
    """
    for symbol, qty in positions.items():
        if qty >= 0:
            continue  # Only check shorts

        entry_price = entry_prices.get(symbol)
        current_price = current_prices.get(symbol)
        if entry_price is None or current_price is None or entry_price <= 0:
            continue

        notional = abs(qty) * entry_price
        unrealized_loss = abs(qty) * (current_price - entry_price)

        if unrealized_loss <= 0:
            continue  # Short is profitable

        if unrealized_loss >= notional * short_loss_limit_pct:
            return False, (
                f"Short {symbol}: loss ${unrealized_loss:.0f} "
                f">= {short_loss_limit_pct * 100:.0f}% of notional ${notional:.0f} "
                f"(entry={entry_price:.2f}, now={current_price:.2f})"
            )

    return True, ""
