# Completed Items

> Items moved here after fix is committed and pushed.

---

## BUG-2: OrderRequest schema lacks `metadata` field — CRITICAL (was)

**Fix:** Added `metadata: dict = Field(default_factory=dict)` to `OrderRequest` in `shared/schemas.py`.
**Date:** 2026-03-26

---

## BUG-3: `check_position_size` always approves — HIGH (was)

**Fix:** Changed comparison from tautological `estimated_value > total_equity` to `signal.strength * total_equity > total_equity * max_pct`. Added `test_rejects_oversized` test.
**Date:** 2026-03-26

---

## ARCH-1: DB password not URL-encoded — HIGH (was)

**Fix:** Added `urllib.parse.quote_plus()` for user and password in `db/session.py` `_build_url()`.
**Date:** 2026-03-26

---

## BUG-4: Router logs "FILLED" for non-sim PLACED orders — MEDIUM (was)

**Fix:** Split log path — checks `order.status == FILLED` before logging fill details. Live PLACED orders now log "PLACED" with correct info.
**Date:** 2026-03-26

---

## BUG-5: Backtest `close` field has no mapping — LOW (was)

**Fix:** Added `"close": "Close"` to `col_to_field` in `backtest/engine.py`.
**Date:** 2026-03-26

---

## BUG-6: Reconciler broken in multi-session mode — MEDIUM (was)

**Fix:** Added `session_id` param to `Reconciler.__init__()`, uses `_session_channel()` for Redis key. Also documented that reconciler is not wired into V2 SessionPipeline (legacy only).
**Date:** 2026-03-26

---

## ERR-1: Silent `pass` on Redis state refresh failure — HIGH (was)

**Fix:** Replaced `except: pass` with `logger.warning()` including exc_info in `risk/manager.py` `_refresh_portfolio_state()`.
**Date:** 2026-03-26

---

## CONC-1: SimulationAdapter state not thread-safe — HIGH (was)

**Fix:** Added `asyncio.Lock` guarding `_cash`, `_positions`, `_last_prices` in both `_on_price_update` and `place_order` in `execution/sim_adapter.py`.
**Date:** 2026-03-26

---

## CQ-1: Duplicate `ValidationResult` class — MEDIUM (was)

**Fix:** Extracted `ValidationResult` dataclass to `shared/schemas.py`. Both `strategy/validator_v2.py` and `strategy/custom_validator.py` now import from there.
**Date:** 2026-03-26
