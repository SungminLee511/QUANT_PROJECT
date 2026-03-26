"""Backtesting engine (V2) — replay historical data through a weight-based strategy.

Downloads OHLCV from yfinance, builds rolling numpy buffers matching the user's
data config, calls main(data) every N bars, rebalances portfolio via weights.
No Redis, no DB, no async overhead.
"""

import logging
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import yfinance as yf

from strategy.executor import StrategyExecutor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result containers (unchanged from V1)
# ---------------------------------------------------------------------------

@dataclass
class BacktestTrade:
    """One executed trade during the backtest."""
    timestamp: str
    symbol: str
    side: str          # "buy" / "sell"
    quantity: float
    price: float
    value: float       # dollar value of the trade
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
# Weight-based virtual portfolio
# ---------------------------------------------------------------------------

class _VirtualPortfolio:
    """In-memory portfolio for backtesting — rebalances via target weights."""

    def __init__(self, starting_cash: float, symbols: list[str]):
        self.cash: float = starting_cash
        self.starting_cash: float = starting_cash
        self.symbols = symbols
        self.positions: dict[str, float] = {}  # symbol -> quantity
        self.last_prices: dict[str, float] = {}

    def update_prices(self, prices: dict[str, float]) -> None:
        self.last_prices.update(prices)

    def rebalance(self, target_weights: np.ndarray, date_str: str) -> list[BacktestTrade]:
        """Rebalance to target weights. Returns list of trades executed."""
        trades = []
        total_equity = self.get_equity()
        n = len(self.symbols)

        if target_weights.shape != (n,):
            return trades

        for i, symbol in enumerate(self.symbols):
            price = self.last_prices.get(symbol, 0)
            if price <= 0:
                continue

            target_value = target_weights[i] * total_equity
            current_qty = self.positions.get(symbol, 0.0)
            current_value = current_qty * price
            diff_value = target_value - current_value

            # Skip tiny rebalances (< $1)
            if abs(diff_value) < 1.0:
                continue

            qty = abs(diff_value) / price
            if diff_value > 0:
                # BUY — can't spend more than available cash
                max_buy_value = self.cash
                actual_value = min(abs(diff_value), max_buy_value)
                if actual_value < 1.0:
                    continue
                qty = actual_value / price
                self.cash -= qty * price
                self.positions[symbol] = self.positions.get(symbol, 0.0) + qty
                trades.append(BacktestTrade(
                    timestamp=date_str, symbol=symbol, side="buy",
                    quantity=round(qty, 8), price=round(price, 6),
                    value=round(qty * price, 2),
                    cash_after=round(self.cash, 2),
                    equity_after=round(self.get_equity(), 2),
                ))
            else:
                # SELL — can't sell more than we have
                max_sell_qty = self.positions.get(symbol, 0.0)
                qty = min(qty, max_sell_qty)
                if qty <= 0:
                    continue
                self.cash += qty * price
                self.positions[symbol] = self.positions.get(symbol, 0.0) - qty
                if self.positions[symbol] < 1e-10:
                    self.positions.pop(symbol, None)
                trades.append(BacktestTrade(
                    timestamp=date_str, symbol=symbol, side="sell",
                    quantity=round(qty, 8), price=round(price, 6),
                    value=round(qty * price, 2),
                    cash_after=round(self.cash, 2),
                    equity_after=round(self.get_equity(), 2),
                ))

        return trades

    def get_equity(self) -> float:
        positions_val = sum(
            qty * self.last_prices.get(sym, 0)
            for sym, qty in self.positions.items()
        )
        return self.cash + positions_val

    def get_positions_value(self) -> float:
        return self.get_equity() - self.cash


# ---------------------------------------------------------------------------
# Data download (reused from V1)
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
                cl = col.lower()
                if cl in ("date", "datetime"):
                    rename_map[col] = "Date"
                elif cl == "open":
                    rename_map[col] = "Open"
                elif cl == "high":
                    rename_map[col] = "High"
                elif cl == "low":
                    rename_map[col] = "Low"
                elif cl == "close":
                    rename_map[col] = "Close"
                elif cl == "volume":
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
# Rolling buffer builder
# ---------------------------------------------------------------------------

def _build_data_snapshot(
    buffers: dict[str, np.ndarray],
    fill_counts: dict[str, int],
    fields: dict[str, int],
    symbols: list[str],
) -> dict[str, np.ndarray] | None:
    """Slice rolling buffers to lookback sizes. Returns None if not enough data."""
    result = {}
    for field_name, lookback in fields.items():
        if fill_counts.get(field_name, 0) < lookback:
            return None
        buf = buffers[field_name]
        result[field_name] = buf[:, -lookback:].copy()
    result["tickers"] = symbols
    return result


def _append_to_buffer(buffers: dict[str, np.ndarray],
                       fill_counts: dict[str, int],
                       field_name: str,
                       values: np.ndarray) -> None:
    """Shift buffer left and write new values."""
    buf = buffers[field_name]
    buf[:, :-1] = buf[:, 1:]
    buf[:, -1] = values
    fill_counts[field_name] = min(fill_counts[field_name] + 1, buf.shape[1])


# ---------------------------------------------------------------------------
# Metrics calculation (reused from V1, adapted for weight-based trades)
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

    # Trade analysis — group buy/sell pairs per symbol
    metrics.total_trades = len(trades)
    if trades:
        wins = []
        losses = []
        buy_prices: dict[str, list[float]] = {}

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
                    buy_prices[t.symbol] = []

        metrics.winning_trades = len(wins)
        metrics.losing_trades = len(losses)
        total_closed = len(wins) + len(losses)
        if total_closed > 0:
            metrics.win_rate_pct = round(len(wins) / total_closed * 100, 1)
        if wins:
            metrics.avg_win_pct = round(sum(wins) / len(wins), 2)
        if losses:
            metrics.avg_loss_pct = round(sum(losses) / len(losses), 2)
        gross_wins = sum(wins) if wins else 0
        gross_losses = abs(sum(losses)) if losses else 0
        if gross_losses > 0:
            metrics.profit_factor = round(gross_wins / gross_losses, 2)
        elif gross_wins > 0:
            metrics.profit_factor = 9999.99  # BUG-23 fix: avoid inf which breaks JSON

    return metrics


# ---------------------------------------------------------------------------
# Main backtest runner (V2)
# ---------------------------------------------------------------------------

def run_backtest(
    strategy_code: str,
    symbols: list[str],
    start_date: str,
    end_date: str,
    starting_cash: float = 10000.0,
    interval: str = "1d",
    data_config: dict | None = None,
) -> BacktestResult:
    """Run a V2 weight-based backtest.

    Args:
        strategy_code: Python source containing main(data) function.
        symbols: List of ticker symbols.
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
        starting_cash: Initial cash.
        interval: yfinance bar interval (1d, 1wk, 1mo, 1h, etc.).
        data_config: Optional data config dict. If None, uses default (price:20, volume:10).

    Returns:
        BacktestResult with equity curve, trades, and metrics.
    """
    result = BacktestResult()

    # 1. Parse data config
    if data_config is None:
        data_config = {
            "resolution": interval,
            "exec_every_n": 1,
            "fields": {
                "price": {"enabled": True, "lookback": 20},
                "volume": {"enabled": True, "lookback": 10},
            },
        }

    exec_every_n = max(1, data_config.get("exec_every_n", 1))

    # Determine enabled fields and lookbacks
    fields: dict[str, int] = {}
    for fname, fcfg in data_config.get("fields", {}).items():
        if isinstance(fcfg, dict) and fcfg.get("enabled") and fcfg.get("lookback", 0) > 0:
            fields[fname] = fcfg["lookback"]
        elif isinstance(fcfg, int) and fcfg > 0:
            fields[fname] = fcfg

    if not fields:
        fields = {"price": 20}

    # 2. Load strategy
    executor = StrategyExecutor(session_id="backtest", symbols=symbols)
    try:
        executor.load_strategy(strategy_code)
    except Exception as e:
        result.errors.append(f"Failed to load strategy: {e}")
        return result

    # 3. Download historical data
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

    # 4. Initialize portfolio and rolling buffers
    portfolio = _VirtualPortfolio(starting_cash, symbols)
    n_symbols = len(symbols)

    # Map of OHLCV column names → field names
    col_to_field = {
        "price": "Close", "close": "Close", "open": "Open", "high": "High",
        "low": "Low", "volume": "Volume",
    }

    # BUG-24 fix: track previous close per symbol for day_change_pct
    prev_close = np.full(n_symbols, np.nan, dtype=np.float64)

    buffers: dict[str, np.ndarray] = {}
    fill_counts: dict[str, int] = {}
    for fname, lookback in fields.items():
        buf_size = lookback + 10
        buffers[fname] = np.full((n_symbols, buf_size), np.nan, dtype=np.float64)
        fill_counts[fname] = 0

    # 5. Build symbol-to-index mapping
    sym_to_idx = {s: i for i, s in enumerate(symbols)}

    # 6. Walk through dates chronologically
    grouped = data.groupby("Date")
    dates_sorted = sorted(grouped.groups.keys())

    bar_count = 0

    for date in dates_sorted:
        day_data = grouped.get_group(date)
        date_str = pd.Timestamp(date).strftime("%Y-%m-%d")

        # Build arrays for this bar: one value per symbol
        bar_values: dict[str, np.ndarray] = {}
        for fname in fields:
            bar_values[fname] = np.full(n_symbols, np.nan)

        prices_this_bar: dict[str, float] = {}

        for _, row in day_data.iterrows():
            symbol = row["Symbol"]
            idx = sym_to_idx.get(symbol)
            if idx is None:
                continue

            price = float(row["Close"])
            prices_this_bar[symbol] = price

            for fname in fields:
                col = col_to_field.get(fname)
                if col and col in row:
                    val = float(row[col]) if pd.notna(row[col]) else 0.0
                    bar_values[fname][idx] = val

            # VWAP approximation (HLC/3) if requested
            if "vwap" in fields:
                h = float(row["High"]) if pd.notna(row.get("High")) else price
                l = float(row["Low"]) if pd.notna(row.get("Low")) else price
                bar_values["vwap"][idx] = (h + l + price) / 3

            # BUG-24 fix: day_change_pct = (close - prev_close) / prev_close * 100
            if "day_change_pct" in fields:
                if not np.isnan(prev_close[idx]) and prev_close[idx] != 0:
                    bar_values["day_change_pct"][idx] = (price - prev_close[idx]) / prev_close[idx] * 100
                else:
                    bar_values["day_change_pct"][idx] = 0.0

        # Update portfolio prices
        portfolio.update_prices(prices_this_bar)

        # BUG-24: update prev_close for next bar's day_change_pct
        for sym, price in prices_this_bar.items():
            idx = sym_to_idx[sym]
            prev_close[idx] = price

        # Fill NaN with previous values; keep NaN if no prior data (BUG-25 fix)
        for fname in fields:
            vals = bar_values[fname]
            for i in range(n_symbols):
                if np.isnan(vals[i]):
                    # Use last known value from buffer
                    if fill_counts[fname] > 0:
                        prev_val = buffers[fname][i, -1]
                        if not np.isnan(prev_val):
                            vals[i] = prev_val

        # Append to rolling buffers
        for fname in fields:
            _append_to_buffer(buffers, fill_counts, fname, bar_values[fname])

        bar_count += 1

        # Run strategy every N bars
        if bar_count % exec_every_n == 0:
            snapshot = _build_data_snapshot(buffers, fill_counts, fields, symbols)
            if snapshot is not None:
                try:
                    weights = executor.execute(snapshot)
                    new_trades = portfolio.rebalance(weights, date_str)
                    result.trades.extend(new_trades)
                except Exception as e:
                    result.errors.append(f"Strategy error on {date_str}: {e}")

        # Record equity at end of bar
        equity = portfolio.get_equity()
        result.equity_curve.append({
            "date": date_str,
            "equity": round(equity, 2),
            "cash": round(portfolio.cash, 2),
            "positions_value": round(portfolio.get_positions_value(), 2),
        })

    # 7. Compute metrics
    result.metrics = _compute_metrics(result.equity_curve, result.trades, starting_cash)
    result.success = True

    logger.info(
        "Backtest complete: %s symbols, %d bars, %d trades, return=%.2f%%",
        symbols, len(dates_sorted), len(result.trades), result.metrics.total_return_pct,
    )

    return result


_BACKTEST_POOL: "concurrent.futures.ThreadPoolExecutor | None" = None
_BACKTEST_SEMAPHORE: "asyncio.Semaphore | None" = None

# Max concurrent backtests — prevents starving the default thread pool
# used by live sessions for DB queries, yfinance calls, etc.
MAX_CONCURRENT_BACKTESTS = 2


def _get_backtest_pool() -> "concurrent.futures.ThreadPoolExecutor":
    """Lazily create a dedicated thread pool for backtests."""
    global _BACKTEST_POOL
    if _BACKTEST_POOL is None:
        import concurrent.futures
        _BACKTEST_POOL = concurrent.futures.ThreadPoolExecutor(
            max_workers=MAX_CONCURRENT_BACKTESTS,
            thread_name_prefix="backtest",
        )
    return _BACKTEST_POOL


def _get_backtest_semaphore() -> "asyncio.Semaphore":
    """Lazily create a semaphore to cap concurrent backtests."""
    global _BACKTEST_SEMAPHORE
    if _BACKTEST_SEMAPHORE is None:
        import asyncio
        _BACKTEST_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_BACKTESTS)
    return _BACKTEST_SEMAPHORE


async def run_backtest_async(
    strategy_code: str,
    symbols: list[str],
    start_date: str,
    end_date: str,
    starting_cash: float = 10000.0,
    interval: str = "1d",
    data_config: dict | None = None,
) -> BacktestResult:
    """Async entry point — runs the sync backtest in a dedicated thread pool.

    Uses a separate ThreadPoolExecutor (not the default) so that concurrent
    backtests don't starve live session tasks (DB queries, data fetches, etc.).
    A semaphore caps concurrent backtests to MAX_CONCURRENT_BACKTESTS.
    """
    import asyncio

    sem = _get_backtest_semaphore()
    if not sem.locked():
        pass  # fast path — slot available
    else:
        logger.info("Backtest queued — %d already running", MAX_CONCURRENT_BACKTESTS)

    async with sem:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _get_backtest_pool(),
            lambda: run_backtest(
                strategy_code=strategy_code,
                symbols=symbols,
                start_date=start_date,
                end_date=end_date,
                starting_cash=starting_cash,
                interval=interval,
                data_config=data_config,
            ),
        )
