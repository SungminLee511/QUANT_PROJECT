"""Tests for custom data function validator."""

import pytest

from strategy.custom_validator import validate_custom_data_function


VALID_PER_STOCK = '''
import numpy as np
import requests

def fetch(tickers: list[str]) -> "np.ndarray":
    result = []
    for t in tickers:
        result.append(0.0)
    return np.array(result)
'''

VALID_GLOBAL = '''
def fetch() -> float:
    return 18.5
'''


class TestCustomDataValidator:
    def test_valid_per_stock(self):
        r = validate_custom_data_function(VALID_PER_STOCK, "per_stock")
        assert r.valid is True

    def test_valid_global(self):
        r = validate_custom_data_function(VALID_GLOBAL, "global")
        assert r.valid is True

    def test_allows_requests_import(self):
        """Custom data functions can use requests (unlike strategy code)."""
        code = "import requests\ndef fetch(tickers): return [0.0]"
        r = validate_custom_data_function(code, "per_stock")
        assert r.valid is True

    def test_blocks_subprocess(self):
        code = "import subprocess\ndef fetch(tickers): pass"
        r = validate_custom_data_function(code, "per_stock")
        assert r.valid is False

    def test_blocks_os(self):
        code = "import os\ndef fetch(tickers): return os.listdir('.')"
        r = validate_custom_data_function(code, "per_stock")
        assert r.valid is False

    def test_no_fetch_function(self):
        code = "def compute(x): return x"
        r = validate_custom_data_function(code, "per_stock")
        assert r.valid is False
        assert any("fetch" in e for e in r.errors)

    def test_wrong_param_per_stock(self):
        code = "def fetch(symbols): return []"
        r = validate_custom_data_function(code, "per_stock")
        assert r.valid is False
        assert any("tickers" in e for e in r.errors)

    def test_global_must_have_no_params(self):
        code = "def fetch(x): return 0.0"
        r = validate_custom_data_function(code, "global")
        assert r.valid is False

    def test_syntax_error(self):
        r = validate_custom_data_function("def fetch(\n", "per_stock")
        assert r.valid is False
        assert any("Syntax" in e for e in r.errors)
