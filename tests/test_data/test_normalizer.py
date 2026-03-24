"""Tests for data normalizer functions."""

from data.normalizer import normalize_binance_trade, normalize_binance_kline
from shared.enums import Exchange


class TestBinanceNormalizer:
    def test_normalize_trade(self):
        msg = {"s": "BTCUSDT", "p": "50000.50", "q": "0.5", "T": 1700000000000}
        tick = normalize_binance_trade(msg)
        assert tick.symbol == "BTCUSDT"
        assert tick.price == 50000.50
        assert tick.volume == 0.5
        assert tick.exchange == Exchange.BINANCE

    def test_normalize_kline_closed(self):
        msg = {
            "k": {
                "s": "BTCUSDT",
                "i": "1m",
                "o": "50000",
                "h": "50100",
                "l": "49900",
                "c": "50050",
                "v": "100",
                "t": 1700000000000,
                "x": True,
            }
        }
        bar = normalize_binance_kline(msg)
        assert bar is not None
        assert bar.symbol == "BTCUSDT"
        assert bar.close == 50050.0
        assert bar.interval == "1m"

    def test_normalize_kline_not_closed(self):
        msg = {
            "k": {
                "s": "BTCUSDT",
                "i": "1m",
                "o": "50000",
                "h": "50100",
                "l": "49900",
                "c": "50050",
                "v": "100",
                "t": 1700000000000,
                "x": False,
            }
        }
        bar = normalize_binance_kline(msg)
        assert bar is None
