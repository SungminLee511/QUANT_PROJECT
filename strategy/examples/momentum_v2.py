"""Default momentum strategy (V2) — long stocks above rolling mean, short below.

Required data config:
    price: lookback >= 2
"""
import numpy as np


def main(data: dict) -> np.ndarray:
    """
    Simple momentum: deviation from rolling mean price.
    Positive deviation → long, negative → short.
    Output is auto-normalized so sum(|weights|) = 1.

    Args:
        data: dict with keys matching configured data fields.
              data["price"] is np.ndarray of shape [N, lookback].
              data["tickers"] is list[str] of length N.

    Returns:
        np.ndarray of shape [N] — portfolio weights per stock.
    """
    prices = data["price"]              # [N, lookback]
    current = prices[:, -1]             # [N]
    mean = prices.mean(axis=1)          # [N]

    # Avoid division by zero
    safe_mean = np.where(mean != 0, mean, 1.0)
    deviation = (current - safe_mean) / safe_mean  # [N]

    return deviation
