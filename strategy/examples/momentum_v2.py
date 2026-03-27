"""Default momentum strategy (V2) — long-only, fully invested.

Required data config:
    price: lookback >= 2
"""
import numpy as np


def main(data: dict) -> np.ndarray:
    """
    Simple momentum: allocate more weight to stocks with higher
    relative strength (price above rolling mean).

    Each weight is in [0, 1] and all weights sum to exactly 1.0,
    meaning the portfolio is always fully invested with no cash.

    Args:
        data: dict with keys matching configured data fields.
              data["price"] is np.ndarray of shape [N, lookback].
              data["tickers"] is list[str] of length N.

    Returns:
        np.ndarray of shape [N] — portfolio weights per stock, sum = 1.
    """
    prices = data["price"]              # [N, lookback]
    n = prices.shape[0]

    # Handle NaN: use nanmean to ignore missing values
    current = prices[:, -1]             # [N]
    mean = np.nanmean(prices, axis=1)   # [N]

    # If any current price is NaN, fall back to equal-weight
    if np.any(np.isnan(current)) or np.any(np.isnan(mean)):
        return np.ones(n) / n

    # Avoid division by zero
    safe_mean = np.where(mean != 0, mean, 1.0)
    deviation = (current - safe_mean) / safe_mean  # [N]

    # Shift to non-negative: subtract the minimum so all values >= 0
    shifted = deviation - np.nanmin(deviation)

    # If all deviations are identical (all zero), equal-weight
    total = np.nansum(shifted)
    if total == 0:
        weights = np.ones(n) / n
    else:
        weights = shifted / total  # each in [0,1], sum = 1.0

    return weights
