"""HTTP retry helper with exponential backoff and 429 rate-limit handling.

BUG-86: All data sources previously had no retry logic. A single transient
failure or rate-limit hit caused complete data loss for that scrape cycle.
"""

import logging
import time
from typing import Callable, TypeVar

import requests

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Defaults
MAX_RETRIES = 3
INITIAL_BACKOFF_SEC = 0.5
BACKOFF_MULTIPLIER = 2.0
MAX_BACKOFF_SEC = 10.0


def retry_request(
    session: requests.Session,
    method: str,
    url: str,
    *,
    max_retries: int = MAX_RETRIES,
    initial_backoff: float = INITIAL_BACKOFF_SEC,
    timeout: float = 10.0,
    **kwargs,
) -> requests.Response:
    """Execute an HTTP request with retry and exponential backoff.

    Retries on:
    - ConnectionError, Timeout (transient network issues)
    - HTTP 429 (rate limited) — respects Retry-After header
    - HTTP 5xx (server errors)

    Does NOT retry on:
    - HTTP 4xx (except 429) — client errors are not transient

    Args:
        session: requests.Session to use.
        method: HTTP method ("get", "post", etc.).
        url: Request URL.
        max_retries: Maximum number of retry attempts.
        initial_backoff: Initial backoff in seconds (doubles each retry).
        timeout: Request timeout in seconds.
        **kwargs: Passed to session.request().

    Returns:
        requests.Response on success.

    Raises:
        Last exception if all retries exhausted.
    """
    kwargs.setdefault("timeout", timeout)
    backoff = initial_backoff
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            resp = session.request(method, url, **kwargs)

            # Success or non-retryable client error
            if resp.status_code < 500 and resp.status_code != 429:
                return resp

            # 429 Rate Limited
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait = min(float(retry_after), MAX_BACKOFF_SEC)
                    except ValueError:
                        wait = backoff
                else:
                    wait = backoff
                if attempt < max_retries:
                    logger.warning(
                        "Rate limited (429) on %s — retry %d/%d after %.1fs",
                        url, attempt + 1, max_retries, wait,
                    )
                    time.sleep(wait)
                    backoff = min(backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF_SEC)
                    continue
                resp.raise_for_status()

            # 5xx Server Error
            if attempt < max_retries:
                logger.warning(
                    "Server error %d on %s — retry %d/%d after %.1fs",
                    resp.status_code, url, attempt + 1, max_retries, backoff,
                )
                time.sleep(backoff)
                backoff = min(backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF_SEC)
                continue
            resp.raise_for_status()

        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt < max_retries:
                logger.warning(
                    "Network error on %s (%s) — retry %d/%d after %.1fs",
                    url, type(exc).__name__, attempt + 1, max_retries, backoff,
                )
                time.sleep(backoff)
                backoff = min(backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF_SEC)
                continue
            raise

    # Should not reach here, but just in case
    if last_exc:
        raise last_exc
    raise RuntimeError(f"Retry exhausted for {url}")
