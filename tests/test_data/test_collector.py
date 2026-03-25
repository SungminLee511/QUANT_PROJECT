"""Tests for DataCollector — rolling buffers, snapshots, custom data loading."""

import numpy as np
import pytest

from shared.enums import Exchange
from data.collector import DataCollector


class TestDataCollectorBuffers:
    """Test buffer initialization and snapshot logic (no network calls)."""

    def _make_config(self, fields=None, resolution="1min", exec_every_n=1):
        if fields is None:
            fields = {"price": {"enabled": True, "lookback": 5}}
        return {
            "resolution": resolution,
            "exec_every_n": exec_every_n,
            "fields": fields,
            "custom_data": [],
            "custom_global_data": [],
        }

    def test_init_creates_buffers(self):
        config = self._make_config({"price": {"enabled": True, "lookback": 10}})
        dc = DataCollector("s1", ["A", "B"], config, Exchange.ALPACA)
        assert "price" in dc._buffers
        assert dc._buffers["price"].shape == (2, 20)  # lookback + 10 padding
        assert dc._buffer_fill["price"] == 0

    def test_disabled_fields_excluded(self):
        config = self._make_config({
            "price": {"enabled": True, "lookback": 5},
            "volume": {"enabled": False, "lookback": 10},
        })
        dc = DataCollector("s1", ["A"], config, Exchange.ALPACA)
        assert "price" in dc.fields
        assert "volume" not in dc.fields

    def test_append_and_snapshot(self):
        config = self._make_config({"price": {"enabled": True, "lookback": 3}})
        dc = DataCollector("s1", ["A", "B"], config, Exchange.ALPACA)

        # Not enough data yet
        assert dc.get_data_snapshot() is None

        # Append 3 bars
        for i in range(3):
            vals = np.array([100.0 + i, 200.0 + i])
            dc._append_to_buffer("price", vals)

        snapshot = dc.get_data_snapshot()
        assert snapshot is not None
        assert snapshot["price"].shape == (2, 3)
        assert snapshot["price"][0, -1] == 102.0
        assert snapshot["tickers"] == ["A", "B"]

    def test_get_current_prices(self):
        config = self._make_config()
        dc = DataCollector("s1", ["A", "B"], config, Exchange.ALPACA)

        # No prices yet
        assert dc.get_current_prices() is None

        # Append one bar
        dc._append_to_buffer("price", np.array([150.0, 250.0]))
        prices = dc.get_current_prices()
        assert prices is not None
        np.testing.assert_array_equal(prices, [150.0, 250.0])

    def test_custom_data_buffer_per_stock(self):
        config = {
            "resolution": "1min",
            "exec_every_n": 1,
            "fields": {"price": {"enabled": True, "lookback": 3}},
            "custom_data": [{"name": "rsi", "lookback": 2}],
            "custom_global_data": [],
        }
        dc = DataCollector("s1", ["A", "B"], config, Exchange.ALPACA)
        assert "rsi" in dc._buffers
        assert dc._buffers["rsi"].shape == (2, 12)  # lookback 2 + 10

    def test_custom_data_buffer_global(self):
        config = {
            "resolution": "1min",
            "exec_every_n": 1,
            "fields": {"price": {"enabled": True, "lookback": 3}},
            "custom_data": [],
            "custom_global_data": [{"name": "vix", "lookback": 5}],
        }
        dc = DataCollector("s1", ["A", "B"], config, Exchange.ALPACA)
        assert "vix" in dc._buffers
        assert dc._buffers["vix"].shape == (1, 15)  # [1, lookback+10]

    def test_fallback_to_price_if_no_fields(self):
        config = self._make_config(fields={})
        dc = DataCollector("s1", ["A"], config, Exchange.ALPACA)
        assert "price" in dc.fields
        assert dc.fields["price"] == 20


class TestDataCollectorCustomFunctions:
    def test_load_per_stock_function(self):
        config = {
            "resolution": "1min",
            "exec_every_n": 1,
            "fields": {"price": {"enabled": True, "lookback": 3}},
            "custom_data": [{"name": "test_data", "lookback": 2}],
            "custom_global_data": [],
        }
        dc = DataCollector("s1", ["A", "B"], config, Exchange.ALPACA)
        dc.load_custom_data_functions([{
            "name": "test_data",
            "type": "per_stock",
            "code": "def fetch(tickers):\n    import numpy as np\n    return np.ones(len(tickers))",
        }])
        assert "test_data" in dc._custom_data_fns

    def test_load_global_function(self):
        config = {
            "resolution": "1min",
            "exec_every_n": 1,
            "fields": {"price": {"enabled": True, "lookback": 3}},
            "custom_data": [],
            "custom_global_data": [{"name": "vix", "lookback": 5}],
        }
        dc = DataCollector("s1", ["A"], config, Exchange.ALPACA)
        dc.load_custom_data_functions([{
            "name": "vix",
            "type": "global",
            "code": "def fetch():\n    return 18.5",
        }])
        assert "vix" in dc._custom_global_fns

    def test_invalid_code_skipped(self):
        config = {
            "resolution": "1min",
            "exec_every_n": 1,
            "fields": {"price": {"enabled": True, "lookback": 3}},
            "custom_data": [{"name": "bad", "lookback": 2}],
            "custom_global_data": [],
        }
        dc = DataCollector("s1", ["A"], config, Exchange.ALPACA)
        dc.load_custom_data_functions([{
            "name": "bad",
            "type": "per_stock",
            "code": "this is not valid python!!!",
        }])
        assert "bad" not in dc._custom_data_fns
