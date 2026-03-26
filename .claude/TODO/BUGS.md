# Bugs — Open Issues

> Last verified against code: 2026-03-26. All items confirmed still present.

---

## BUG-3: `check_position_size` always approves — HIGH

**File:** `risk/limits.py` (lines 30–33)

```python
estimated_value = total_equity * max_pct   # e.g. 10000 * 0.10 = 1000
if estimated_value > total_equity:          # 1000 > 10000 → always False
```

The risk check is a no-op — it compares the *limit* against equity, not the *proposed position* against the limit.

**Fix:** Compare actual signal/position value: `if position_value > total_equity * max_pct`.

---

## BUG-4: Router logs "FILLED" for non-sim PLACED orders — MEDIUM

**File:** `execution/router.py` (lines 139–147)

After a real (non-sim) order is placed, code falls through to log publishing which always says "FILLED" and references `order.filled_quantity` (which is 0.0 for a just-PLACED order). Misleading logs + zero qty/price in fill records.

**Fix:** Only log fill info for sim orders or after confirmed fill status check.

---

## BUG-5: Backtest `close` field has no mapping — LOW

**File:** `backtest/engine.py` (line 442)

```python
col_to_field = {
    "price": "Close", "open": "Open", "high": "High",
    "low": "Low", "volume": "Volume",
    # Missing: "close": "Close"
}
```

`"close"` is a valid field in `data/sources/__init__.py` (line 66), but backtest engine has no mapping for it. Strategy using `data["close"]` gets NaN buffer.

**Fix:** Add `"close": "Close"` to the mapping dict.

---

## BUG-6: Reconciler completely broken in multi-session mode — MEDIUM

**File:** `portfolio/reconciler.py` (lines 13–51)

Two problems:
1. `__init__` has no `session_id` parameter
2. Reads hardcoded `"portfolio:state"` key instead of `session_channel(session_id, "portfolio:state")`

In multi-session mode, reconciler reads wrong/empty state and can never match any session's actual portfolio.

**Fix:** Add `session_id` param to `__init__`, use `session_channel()` for all Redis keys. Or remove reconciler entirely — it's not wired into the V2 `SessionPipeline` and may be dead code.
