"""Tests for V2 strategy validator (main function interface)."""

import pytest

from strategy.validator_v2 import validate_strategy_code


VALID_STRATEGY = '''
import numpy as np

def main(data: dict) -> np.ndarray:
    prices = data["price"]
    return prices[:, -1] - prices.mean(axis=1)
'''

VALID_WITH_MATH = '''
import numpy as np
import math

def main(data: dict) -> np.ndarray:
    prices = data["price"]
    return np.log(prices[:, -1] / prices[:, 0])
'''


class TestValidateStrategyCode:
    def test_valid_code(self):
        r = validate_strategy_code(VALID_STRATEGY)
        assert r.valid is True
        assert r.errors == []

    def test_syntax_error(self):
        r = validate_strategy_code("def main(data)\n  return 1")
        assert r.valid is False
        assert any("Syntax" in e for e in r.errors)

    def test_no_main_function(self):
        r = validate_strategy_code("def compute(x): return x")
        assert r.valid is False
        assert any("main" in e for e in r.errors)

    def test_wrong_parameter_name(self):
        code = "def main(x): return x"
        r = validate_strategy_code(code)
        assert r.valid is False
        assert any("data" in e for e in r.errors)

    def test_async_main_rejected(self):
        code = "import numpy as np\nasync def main(data): return np.zeros(1)"
        r = validate_strategy_code(code)
        assert r.valid is False
        assert any("async" in e.lower() for e in r.errors)

    def test_forbidden_import_os(self):
        code = "import os\ndef main(data): return os.listdir('.')"
        r = validate_strategy_code(code)
        assert r.valid is False
        assert any("os" in e for e in r.errors)

    def test_forbidden_import_subprocess(self):
        code = "import subprocess\ndef main(data): pass"
        r = validate_strategy_code(code)
        assert r.valid is False

    def test_forbidden_name_eval(self):
        code = '''
import numpy as np
def main(data):
    return eval("np.zeros(1)")
'''
        r = validate_strategy_code(code)
        assert r.valid is False
        assert any("eval" in e for e in r.errors)

    def test_allowed_imports(self):
        r = validate_strategy_code(VALID_WITH_MATH)
        assert r.valid is True

    def test_data_key_check_valid(self):
        config = {
            "fields": {"price": {"enabled": True, "lookback": 20}},
        }
        code = '''
import numpy as np
def main(data):
    return data["price"][:, -1]
'''
        r = validate_strategy_code(code, data_config=config)
        assert r.valid is True

    def test_data_key_check_invalid(self):
        config = {
            "fields": {"price": {"enabled": True, "lookback": 20}},
        }
        code = '''
import numpy as np
def main(data):
    return data["volume"][:, -1]
'''
        r = validate_strategy_code(code, data_config=config)
        assert r.valid is False
        assert any("volume" in e for e in r.errors)

    def test_multiple_main_functions_rejected(self):
        code = '''
import numpy as np
def main(data): return np.zeros(1)
def main(data): return np.ones(1)
'''
        r = validate_strategy_code(code)
        assert r.valid is False
        assert any("multiple" in e.lower() or "2" in e for e in r.errors)
