"""Shared test fixtures — mock Redis, mock DB, sample data."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.enums import Exchange, Signal
from shared.schemas import MarketTick, TradeSignal


@pytest.fixture
def sample_config():
    return {
        "app": {"name": "quant-trader", "env": "dev", "log_level": "DEBUG"},
        "redis": {
            "host": "localhost",
            "port": 6379,
            "db": 0,
            "channels": {
                "market_data": "market:ticks",
                "signals": "strategy:signals",
                "orders": "execution:orders",
                "order_updates": "execution:updates",
                "alerts": "monitoring:alerts",
            },
        },
        "binance": {"testnet": True, "symbols": ["BTCUSDT"]},
        "alpaca": {"paper": True, "symbols": ["AAPL"]},
        "strategy": {
            "id": "test_momentum",
            "module": "strategy.examples.momentum",
            "class_name": "MomentumStrategy",
            "params": {"lookback": 5, "threshold": 0.01},
        },
        "risk": {
            "max_position_pct": 0.10,
            "max_drawdown_pct": 0.05,
            "max_daily_loss_pct": 0.03,
            "max_open_positions": 10,
            "kill_switch_key": "risk:kill_switch",
        },
        "portfolio": {"base_currency": "USDT", "reconcile_interval_sec": 60},
        "monitoring": {
            "dashboard": {"host": "0.0.0.0", "port": 8080},
            "telegram": {"enabled": False},
        },
    }


@pytest.fixture
def mock_redis():
    """Mock RedisClient for unit tests."""
    redis = AsyncMock()
    redis.connect = AsyncMock()
    redis.disconnect = AsyncMock()
    redis.publish = AsyncMock()
    redis.subscribe = AsyncMock()
    redis.get_flag = AsyncMock(return_value=None)
    redis.set_flag = AsyncMock()
    redis.delete_flag = AsyncMock()
    return redis


@pytest.fixture
def sample_tick():
    return MarketTick(
        symbol="BTCUSDT",
        price=50000.0,
        volume=1.5,
        exchange=Exchange.BINANCE,
    )


@pytest.fixture
def sample_signal():
    return TradeSignal(
        symbol="BTCUSDT",
        signal=Signal.BUY,
        strength=0.8,
        strategy_id="test_strategy",
    )
