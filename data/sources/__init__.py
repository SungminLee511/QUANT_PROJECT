"""Data source registry — defines all available data fields, their sources, and sections."""

from enum import Enum
from dataclasses import dataclass, field as dc_field


class DataSource(str, Enum):
    YFINANCE = "yfinance"
    ALPACA = "alpaca"
    BINANCE = "binance"


class FieldSection(str, Enum):
    LIVE = "live"
    DAILY = "daily"


@dataclass
class FieldDefinition:
    name: str
    label: str
    section: FieldSection
    default_lookback: int
    stock_sources: list  # list of DataSource — empty = not available for stocks
    crypto_sources: list  # list of DataSource — empty = not available for crypto
    description: str = ""


# Master registry of all available fields
FIELD_REGISTRY: list[FieldDefinition] = [
    # ── Live fields ──
    FieldDefinition("price", "Price", FieldSection.LIVE, 20,
        stock_sources=[DataSource.YFINANCE, DataSource.ALPACA],
        crypto_sources=[DataSource.BINANCE],
        description="Last traded price"),
    FieldDefinition("bid", "Bid", FieldSection.LIVE, 5,
        stock_sources=[DataSource.ALPACA],
        crypto_sources=[DataSource.BINANCE],
        description="Best bid price"),
    FieldDefinition("ask", "Ask", FieldSection.LIVE, 5,
        stock_sources=[DataSource.ALPACA],
        crypto_sources=[DataSource.BINANCE],
        description="Best ask price"),
    FieldDefinition("spread", "Spread", FieldSection.LIVE, 5,
        stock_sources=[DataSource.ALPACA],
        crypto_sources=[DataSource.BINANCE],
        description="Ask − Bid spread"),
    FieldDefinition("num_trades", "Num Trades", FieldSection.LIVE, 5,
        stock_sources=[],
        crypto_sources=[DataSource.BINANCE],
        description="Number of trades in period"),

    # ── Daily fields ──
    FieldDefinition("open", "Open", FieldSection.DAILY, 10,
        stock_sources=[DataSource.YFINANCE, DataSource.ALPACA],
        crypto_sources=[DataSource.BINANCE],
        description="Today's opening price"),
    FieldDefinition("high", "High", FieldSection.DAILY, 10,
        stock_sources=[DataSource.YFINANCE, DataSource.ALPACA],
        crypto_sources=[DataSource.BINANCE],
        description="Today's intraday high"),
    FieldDefinition("low", "Low", FieldSection.DAILY, 10,
        stock_sources=[DataSource.YFINANCE, DataSource.ALPACA],
        crypto_sources=[DataSource.BINANCE],
        description="Today's intraday low"),
    FieldDefinition("close", "Close", FieldSection.DAILY, 10,
        stock_sources=[DataSource.YFINANCE, DataSource.ALPACA],
        crypto_sources=[DataSource.BINANCE],
        description="Most recent closing price"),
    FieldDefinition("volume", "Volume", FieldSection.DAILY, 10,
        stock_sources=[DataSource.YFINANCE, DataSource.ALPACA],
        crypto_sources=[DataSource.BINANCE],
        description="Today's trading volume"),
    FieldDefinition("vwap", "VWAP", FieldSection.DAILY, 5,
        stock_sources=[DataSource.ALPACA],
        crypto_sources=[DataSource.BINANCE],
        description="Volume-weighted average price"),
    FieldDefinition("day_change_pct", "Day Change %", FieldSection.DAILY, 5,
        stock_sources=[DataSource.YFINANCE],
        crypto_sources=[DataSource.BINANCE],
        description="Percent change from previous close"),
    FieldDefinition("market_cap", "Market Cap", FieldSection.DAILY, 5,
        stock_sources=[DataSource.YFINANCE],
        crypto_sources=[],
        description="Market capitalization"),
    FieldDefinition("pe_ratio", "P/E Ratio", FieldSection.DAILY, 5,
        stock_sources=[DataSource.YFINANCE],
        crypto_sources=[],
        description="Trailing price-to-earnings ratio"),
    FieldDefinition("week52_high", "52W High", FieldSection.DAILY, 5,
        stock_sources=[DataSource.YFINANCE],
        crypto_sources=[],
        description="52-week high price"),
    FieldDefinition("week52_low", "52W Low", FieldSection.DAILY, 5,
        stock_sources=[DataSource.YFINANCE],
        crypto_sources=[],
        description="52-week low price"),
]

FIELD_MAP: dict[str, FieldDefinition] = {f.name: f for f in FIELD_REGISTRY}


def get_fields_for_exchange(is_crypto: bool) -> list[FieldDefinition]:
    """Return fields available for the given exchange type."""
    if is_crypto:
        return [f for f in FIELD_REGISTRY if f.crypto_sources]
    else:
        return [f for f in FIELD_REGISTRY if f.stock_sources]


def get_default_source(field_name: str, is_crypto: bool) -> str:
    """Return the default data source for a field."""
    fd = FIELD_MAP.get(field_name)
    if not fd:
        return DataSource.YFINANCE.value
    sources = fd.crypto_sources if is_crypto else fd.stock_sources
    return sources[0].value if sources else DataSource.YFINANCE.value


def validate_source(field_name: str, source: str, is_crypto: bool) -> str:
    """Return *source* if it is valid for the field+exchange, else the default.

    Prevents e.g. yfinance being used for a crypto session because the config
    was saved with a stock default.
    """
    fd = FIELD_MAP.get(field_name)
    if not fd:
        return get_default_source(field_name, is_crypto)
    valid = fd.crypto_sources if is_crypto else fd.stock_sources
    valid_names = {s.value for s in valid}
    if source in valid_names:
        return source
    return get_default_source(field_name, is_crypto)
