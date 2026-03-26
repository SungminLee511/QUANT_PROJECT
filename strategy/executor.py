"""Strategy executor — runs user's main(data) function and normalizes output weights."""

import logging
import math
import traceback

import numpy as np

logger = logging.getLogger(__name__)


class StrategyExecutor:
    """Compiles and runs a V2 strategy main() function.

    Usage:
        executor = StrategyExecutor(session_id, symbols)
        executor.load_strategy(code_string)
        weights = executor.execute(data_snapshot)
    """

    def __init__(self, session_id: str, symbols: list[str]):
        self.session_id = session_id
        self.symbols = symbols
        self._main_fn = None
        self._code = ""

    def load_strategy(self, code: str) -> None:
        """Compile user code and extract main() function.

        Raises:
            ValueError: If code doesn't define a main() function.
            SyntaxError: If code has syntax errors.
        """
        self._code = code
        namespace = {
            "np": np,
            "numpy": np,
            "math": math,
            "__builtins__": _safe_builtins(),
        }

        exec(compile(code, "<strategy>", "exec"), namespace)

        if "main" not in namespace or not callable(namespace["main"]):
            raise ValueError("Strategy code must define a callable 'main' function.")

        self._main_fn = namespace["main"]
        logger.info(
            "Strategy loaded for session %s (%d symbols)",
            self.session_id, len(self.symbols),
        )

    def execute(self, data: dict[str, np.ndarray]) -> np.ndarray:
        """Run main(data) and return normalized weights.

        Args:
            data: Dict of data arrays. Each value is [N, lookback] or special key.
                  Always includes "tickers" -> list[str].

        Returns:
            np.ndarray of shape [N] with sum(|w|) = 1, or zeros if strategy errors.
        """
        n = len(self.symbols)

        if self._main_fn is None:
            logger.warning("No strategy loaded for session %s", self.session_id)
            return np.zeros(n)

        try:
            raw = self._main_fn(data)
            weights = np.array(raw, dtype=np.float64).flatten()

            if weights.shape != (n,):
                logger.error(
                    "Session %s: main() returned shape %s, expected (%d,)",
                    self.session_id, weights.shape, n,
                )
                return np.zeros(n)

            # Check for NaN/Inf
            if not np.all(np.isfinite(weights)):
                logger.error(
                    "Session %s: main() returned NaN/Inf values, returning zero weights",
                    self.session_id,
                )
                return np.zeros(n)

            # Normalize so sum(|w|) = 1
            abs_sum = np.sum(np.abs(weights))
            if abs_sum > 0:
                weights = weights / abs_sum
            else:
                weights = np.zeros(n)

            return weights

        except Exception:
            logger.exception(
                "Session %s: strategy main() raised an exception",
                self.session_id,
            )
            return np.zeros(n)


def _safe_builtins() -> dict:
    """Return a restricted set of builtins for strategy execution.

    Security notes (SEC-1):
    - ``type`` is excluded to prevent metaclass-based sandbox escapes
    - ``__import__`` is replaced with a whitelist-only version
    - numpy is provided directly; its ``os`` / ``__builtins__`` attrs are
      still technically reachable, but this is accepted risk for a
      personal-use system.  Full isolation requires subprocess/Wasm sandboxing.
    """
    import builtins

    allowed = {
        # Types and constructors
        "int", "float", "str", "bool", "list", "dict", "tuple", "set",
        "frozenset", "bytes", "bytearray", "complex",
        # Built-in functions (safe)
        "abs", "all", "any", "bin", "chr", "divmod", "enumerate",
        "filter", "format", "hash", "hex", "id", "isinstance",
        "issubclass", "iter", "len", "map", "max", "min", "next",
        "oct", "ord", "pow", "print", "range", "repr", "reversed",
        "round", "slice", "sorted", "sum", "zip",
        # NOTE: 'type' deliberately excluded — can be used for metaclass sandbox escapes
        # NOTE: 'getattr'/'setattr'/'delattr' excluded — already in FORBIDDEN_NAMES
        # Exceptions
        "ValueError", "TypeError", "IndexError", "KeyError",
        "RuntimeError", "StopIteration", "ZeroDivisionError",
        "AttributeError", "Exception", "ArithmeticError",
        # Constants
        "True", "False", "None",
    }

    safe = {k: getattr(builtins, k) for k in allowed if hasattr(builtins, k)}

    # Whitelisted import: only allow safe modules
    _IMPORT_WHITELIST = {
        "numpy", "math", "statistics", "collections", "itertools", "functools",
        "datetime", "decimal", "typing", "logging", "pandas",
    }

    def _restricted_import(name, *args, **kwargs):
        # Allow whitelisted modules and their submodules (e.g. numpy._core._methods)
        top_level = name.split(".")[0]
        if top_level not in _IMPORT_WHITELIST:
            raise ImportError(f"Import of '{name}' is not allowed in strategy code.")
        return builtins.__import__(name, *args, **kwargs)

    safe["__import__"] = _restricted_import
    return safe
