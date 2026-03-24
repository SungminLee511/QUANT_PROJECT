"""Backtesting engine — replay historical OHLCV data through a strategy.

No Redis, no DB, no async overhead required.  Downloads data from yfinance,
instantiates the user's strategy class, feeds bars chronologically, tracks
virtual portfolio, and returns a complete BacktestResult.
"""

import ast
import importlib
import logging
import math
import types
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

from shared.enums import Exchange, Signal, Side
from shared.schemas import MarketTick, OHLCVBar, TradeSignal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class BacktestTrade:
    """One executed trade during the backtest."""
    timestamp: str
    symbol: str
    side: str          # "buy" / "sell"
    quantity: float
    price: float
    cash_after: float
    equity_after: float

    def to_dict(self) -> dict:
        return self.__dict__


@dataclass
class BacktestMetrics:
    """Aggregate performance metrics."""
    total_return_pct: float = 0.0
    annualized_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate_pct: float = 0.0
    profit_factor: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    start_date: str = ""
    end_date: str = ""
    trading_days: int = 0

    def to_dict(self) -> dict:
        return self.__dict__


@dataclass
class BacktestResult:
    """Complete backtest output."""
    metrics: BacktestMetrics = field(default_factory=BacktestMetrics)
    equity_curve: list[dict] = field(default_factory=list)   # [{date, equity, cash, positions_value}]
    trades: list[BacktestTrade] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    success: bool = False

    def to_dict(self) -> dict:
        return {
            "metrics": self.metrics.to_dict(),
            "equity_curve": self.equity_curve,
            "trades": [t.to_dict() for t in self.trades],
            "errors": self.errors,
            "success": self.success,
        }


# ---------------------------------------------------------------------------
# Lightweight portfolio tracker (no Redis / DB needed)
# ---------------------------------------------------------------------------

class _VirtualPortfolio:
    """In-memory portfolio for backtesting — mirrors SimulationAdapter logic."""

    def __init__(self, starting_cash: float):
        self.cash: float = starting_cash
        self.starting_cash: float = starting_cash
        self.positions: dict[str, dict] = {}  # symbol -> {qty, avg_price}
        self.last_prices: dict[str, float] = {}

    def update_price(self, symbol: str, price: float) -> None:
        self.last_prices[symbol] = price

    def execute_signal(self, signal: TradeSignal, price: float) -> BacktestTrade | None:
        """Execute a trade signal.  Returns BacktestTrade or None if rejected."""
        symbol = signal.symbol

        if signal.signal == Signal.BUY:
            return self._buy(symbol, price, signal.strength)
        elif signal.signal == Signal.SELL:
            return self._sell(symbol, price, signal.strength)
        return None

    def _buy(self, symbol: str, price: float, strength: float) -> BacktestTrade | None:
        # Allocate strength * remaining cash (capped to available)
        allocation = self.cash * min(strength, 1.0) * 0.95  # keep 5% reserve
        if allocation < 1.0:
            return None
        qty = allocation / price
        self.cash -= qty * price
        pos = self.positions.setdefault(symbol, {"qty": 0.0, "avg_price": 0.0})
        old_value = pos["qty"] * pos["avg_price"]
        pos["qty"] += qty
        pos["avg_price"] = (old_value + qty * price) / pos["qty"] if pos["qty"] > 0 else price
        equity = self.get_equity()
        return BacktestTrade(
            timestamp="", symbol=symbol, side="buy",
            quantity=round(qty, 8), price=round(price, 6),
            cash_after=round(self.cash, 2), equity_after=round(equity, 2),
        )

    def _sell(self, symbol: str, price: float, strength: float) -> BacktestTrade | None:
        pos = self.positions.get(symbol)
        if not pos or pos["qty"] <= 0:
            return None
        sell_qty = pos["qty"] * min(strength, 1.0)
        if sell_qty <= 0:
            return None
        self.cash += sell_qty * price
        pos["qty"] -= sell_qty
        if pos["qty"] < 1e-8:
            del self.positions[symbol]
        equity = self.get_equity()
        return BacktestTrade(
            timestamp="", symbol=symbol, side="sell",
            quantity=round(sell_qty, 8), price=round(price, 6),
            cash_after=round(self.cash, 2), equity_after=round(equity, 2),
        )

    def get_equity(self) -> float:
        positions_val = sum(
            pos["qty"] * self.last_prices.get(sym, pos["avg_price"])
            for sym, pos in self.positions.items()
        )
        return self.cash + positions_val

    def get_positions_value(self) -> float:
        return self.get_equity() - self.cash


# ---------------------------------------------------------------------------
# Strategy class loader (from source code string)
# ---------------------------------------------------------------------------

def _load_strategy_from_code(source: str, strategy_id: str = "backtest", params: dict | None = None):
    """Compile and instantiate a strategy class from raw Python source code.

    Returns the strategy instance or raises ValueError on error.
    """
    from strategy.base import BaseStrategy

    # Parse + compile
    tree = ast.parse(source)
    code_obj = compile(tree, "<backtest_strategy>", "exec")

    # Create a module namespace with access to project imports
    mod = types.ModuleType("_backtest_strategy")
    mod.__dict__["__builtins__"] = __builtins__

    # Pre-populate allowed imports so the user code's import statements work
    exec(code_obj, mod.__dict__)

    # Find the BaseStrategy subclass
    strategy_cls = None
    for name, obj in mod.__dict__.items():
        if (
            isinstance(obj, type)
            and issubclass(obj, BaseStrategy)
            and obj is not BaseStrategy
        ):
            strategy_cls = obj
            break

    if strategy_cls is None:
        raise ValueError("No BaseStrategy subclass found in strategy code")

    return strategy_cls(strategy_id=strategy_id, params=params or {})


# ---------------------------------------------------------------------------
# Data download
# ---------------------------------------------------------------------------

def download_historical_data(
    symbols: list[str],
    start_date: str,
    end_date: str,
    interval: str = "1d",
) -> pd.DataFrame:
    """Download OHLCV data from yfinance.

    Returns a DataFrame with columns: Date, Symbol, Open, High, Low, Close, Volume.
    Sorted by Date then Symbol.
    """
    all_frames = []
    for symbol in symbols:
        try:
            df = yf.download(
                symbol,
                start=start_date,
                end=end_date,
                interval=interval,
                progress=False,
                auto_adjust=True,
            )
            if df.empty:
                logger.warning("No data for %s (%s to %s)", symbol, start_date, end_date)
                continue

            # Handle multi-level columns from yfinance
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            df = df.reset_index()
            df["Symbol"] = symbol
            # Normalize column names
            rename_map = {}
            for col in df.columns:
                if col.lower() == "date" or col.lower() == "datetime":
                    rename_map[col] = "Date"
                elif col.lower() == "open":
                    rename_map[col] = "Open"
                elif col.lower() == "high":
                    rename_map[col] = "High"
                elif col.lower() == "low":
                    rename_map[col] = "Low"
                elif col.lower() == "close":
                    rename_map[col] = "Close"
                elif col.lower() == "volume":
                    rename_map[col] = "Volume"
            df = df.rename(columns=rename_map)
            all_frames.append(df[["Date", "Symbol", "Open", "High", "Low", "Close", "Volume"]])
        except Exception:
            logger.exception("Failed to download data for %s", symbol)

    if not all_frames:
        return pd.DataFrame(columns=["Date", "Symbol", "Open", "High", "Low", "Close", "Volume"])

    result = pd.concat(all_frames, ignore_index=True)
    result = result.sort_values(["Date", "Symbol"]).reset_index(drop=True)
    return result


# ---------------------------------------------------------------------------
# Metrics calculation
# ---------------------------------------------------------------------------

def _compute_metrics(
    equity_curve: list[dict],
    trades: list[BacktestTrade],
    starting_cash: float,
) -> BacktestMetrics:
    """Compute performance metrics from equity curve and trade log."""
    metrics = BacktestMetrics()

    if len(equity_curve) < 2:
        return metrics

    equities = [pt["equity"] for pt in equity_curve]
    dates = [pt["date"] for pt in equity_curve]

    metrics.start_date = dates[0]
    metrics.end_date = dates[-1]
    metrics.trading_days = len(equities)

    # Total return
    final_equity = equities[-1]
    metrics.total_return_pct = round((final_equity / starting_cash - 1) * 100, 2)

    # Annualized return
    if metrics.trading_days > 1:
        years = metrics.trading_days / 252
        if years > 0 and final_equity > 0:
            metrics.annualized_return_pct = round(
                ((final_equity / starting_cash) ** (1 / years) - 1) * 100, 2
            )

    # Daily returns for Sharpe
    daily_returns = []
    for i in range(1, len(equities)):
        if equities[i - 1] > 0:
            daily_returns.append(equities[i] / equities[i - 1] - 1)

    if daily_returns:
        avg_ret = np.mean(daily_returns)
        std_ret = np.std(daily_returns, ddof=1) if len(daily_returns) > 1 else 0
        if std_ret > 0:
            metrics.sharpe_ratio = round(avg_ret / std_ret * math.sqrt(252), 2)

    # Max drawdown
    peak = equities[0]
    max_dd = 0.0
    for eq in equities:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)
    metrics.max_drawdown_pct = round(max_dd * 100, 2)

    # Trade analysis
    metrics.total_trades = len(trades)
    if trades:
        # Group trades into round-trips: buy then sell
        # Simple approach: track P&L per sell
        wins = []
        losses = []
        buy_prices: dict[str, list[float]] = {}  # symbol -> list of buy prices

        for t in trades:
            if t.side == "buy":
                buy_prices.setdefault(t.symbol, []).append(t.price)
            elif t.side == "sell":
                buys = buy_prices.get(t.symbol, [])
                if buys:
                    avg_buy = sum(buys) / len(buys)
                    pnl_pct = (t.price / avg_buy - 1) * 100
                    if pnl_pct >= 0:
                        wins.append(pnl_pct)
                    else:
                        losses.append(pnl_pct)
                    buy_prices[t.symbol] = []  # reset after sell

        metrics.winning_trades = len(wins)
        metrics.losing_trades = len(losses)
        total_closed = len(wins) + len(losses)
        if total_closed > 0:
            metrics.win_rate_pct = round(len(wins) / total_closed * 100, 1)
        if wins:
            metrics.avg_win_pct = round(sum(wins) / len(wins), 2)
        if losses:
            metrics.avg_loss_pct = round(sum(losses) / len(losses), 2)
        # Profit factor
        gross_wins = sum(wins) if wins else 0
        gross_losses = abs(sum(losses)) if losses else 0
        if gross_losses > 0:
            metrics.profit_factor = round(gross_wins / gross_losses, 2)
        elif gross_wins > 0:
            metrics.profit_factor = float("inf")

    return metrics


# ---------------------------------------------------------------------------
# Main backtest runner
# ---------------------------------------------------------------------------

import asyncio


async def _run_backtest_async(
    strategy_code: str,
    symbols: list[str],
    start_date: str,
    end_date: str,
    starting_cash: float = 10000.0,
    interval: str = "1d",
    strategy_params: dict | None = None,
) -> BacktestResult:
    """Core async backtest logic.  Called from the sync wrapper."""
    result = BacktestResult()

    # 1. Load strategy from code
    try:
        strategy = _load_strategy_from_code(
            strategy_code,
            strategy_id="backtest",
            params=strategy_params or {},
        )
    except Exception as e:
        result.errors.append(f"Failed to load strategy: {e}")
        return result

    # 2. Download historical data
    try:
        data = download_historical_data(symbols, start_date, end_date, interval)
    except Exception as e:
        result.errors.append(f"Failed to download data: {e}")
        return result

    if data.empty:
        result.errors.append(
            f"No historical data found for {symbols} from {start_date} to {end_date}"
        )
        return result

    # 3. Initialize portfolio
    portfolio = _VirtualPortfolio(starting_cash)

    # 4. Call on_start
    try:
        await strategy.on_start()
    except Exception:
        pass  # on_start is optional

    # 5. Replay bars in chronological order
    grouped = data.groupby("Date")
    dates_sorted = sorted(grouped.groups.keys())

    for date in dates_sorted:
        day_bars = grouped.get_group(date)

        for _, row in day_bars.iterrows():
            symbol = row["Symbol"]
            price = float(row["Close"])
            portfolio.update_price(symbol, price)

            # Build OHLCVBar
            bar = OHLCVBar(
                symbol=symbol,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=price,
                volume=float(row["Volume"]) if pd.notna(row["Volume"]) else 0.0,
                interval=interval,
                timestamp=pd.Timestamp(date).to_pydatetime().replace(tzinfo=timezone.utc),
                exchange=Exchange.ALPACA,  # backtest context
            )

            # Also create a tick from close price for on_tick
            tick = MarketTick(
                symbol=symbol,
                price=price,
                volume=float(row["Volume"]) if pd.notna(row["Volume"]) else 0.0,
                timestamp=bar.timestamp,
                exchange=Exchange.ALPACA,
            )

            # Call strategy
            try:
                signal_bar = await strategy.on_bar(bar)
                signal_tick = await strategy.on_tick(tick)
            except Exception as e:
                result.errors.append(
                    f"Strategy error on {date} {symbol}: {e}"
                )
                continue

            # Process signals (bar signal takes priority)
            for sig in [signal_bar, signal_tick]:
                if sig is not None and sig.signal != Signal.HOLD:
                    trade = portfolio.execute_signal(sig, price)
                    if trade:
                        date_str = pd.Timestamp(date).strftime("%Y-%m-%d")
                        trade.timestamp = date_str
                        result.trades.append(trade)

        # Record equity at end of day
        date_str = pd.Timestamp(date).strftime("%Y-%m-%d")
        equity = portfolio.get_equity()
        result.equity_curve.append({
            "date": date_str,
            "equity": round(equity, 2),
            "cash": round(portfolio.cash, 2),
            "positions_value": round(portfolio.get_positions_value(), 2),
        })

    # 6. Call on_stop
    try:
        await strategy.on_stop()
    except Exception:
        pass

    # 7. Compute metrics
    result.metrics = _compute_metrics(result.equity_curve, result.trades, starting_cash)
    result.success = True

    logger.info(
        "Backtest complete: %s symbols, %d bars, %d trades, return=%.2f%%",
        symbols, len(data), len(result.trades), result.metrics.total_return_pct,
    )

    return result


def run_backtest(
    strategy_code: str,
    symbols: list[str],
    start_date: str,
    end_date: str,
    starting_cash: float = 10000.0,
    interval: str = "1d",
    strategy_params: dict | None = None,
) -> BacktestResult:
    """Synchronous entry point for backtesting.

    Creates a new event loop to run the async strategy methods.
    Use run_backtest_async() if already inside an event loop.
    """
    return asyncio.run(_run_backtest_async(
        strategy_code=strategy_code,
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        starting_cash=starting_cash,
        interval=interval,
        strategy_params=strategy_params,
    ))


async def run_backtest_async(
    strategy_code: str,
    symbols: list[str],
    start_date: str,
    end_date: str,
    starting_cash: float = 10000.0,
    interval: str = "1d",
    strategy_params: dict | None = None,
) -> BacktestResult:
    """Async entry point — use when already inside an event loop (e.g. FastAPI)."""
    return await _run_backtest_async(
        strategy_code=strategy_code,
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        starting_cash=starting_cash,
        interval=interval,
        strategy_params=strategy_params,
    )
