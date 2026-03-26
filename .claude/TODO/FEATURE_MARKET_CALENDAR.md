# Feature: Market Calendar + Session Scheduling

> **Priority:** HIGH — Without this, Alpaca equity sessions are broken outside market hours (stale data, rejected orders).

---

## Problem

The system runs 24/7 regardless of exchange. For US equities (Alpaca):
- DataCollector keeps scraping stale prices outside 9:30 AM – 4:00 PM ET
- Strategy runs on stale data, generates meaningless weights
- Rebalancer sends orders that Alpaca rejects or queues for next open
- No way to auto-liquidate before close or pause overnight

Crypto (Binance) is fine — 24/7 market.

---

## Design

### User-Facing Concept

Each session gets a **schedule mode** (stored in DB, configurable via API/UI):

| Mode | Behavior | Use Case |
|------|----------|----------|
| `always_on` | Run 24/7, no pauses. Default for Binance. | Crypto |
| `market_hours` | Pause collection + strategy outside market hours. Hold positions overnight. | Swing/position trading |
| `market_hours_liquidate` | Same as above, but flatten all positions 5 min before close. | Day trading |

### Architecture

```
                         ┌─────────────────┐
                         │  MarketCalendar  │  (knows open/close times per exchange)
                         └────────┬────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              │                   │                   │
     DataCollector        SessionScheduler      BacktestEngine
     (pause/resume)      (auto start/stop)     (skip non-market days)
```

**Three new components:**
1. **`MarketCalendar`** — Pure data: "is market open right now?" and "when does it close?"
2. **`SessionScheduler`** — Background task in SessionManager that checks calendar and triggers actions
3. **DataCollector integration** — Pauses scraping when market is closed

---

## Implementation Plan

### Step 1: `shared/market_calendar.py` (NEW FILE)

Pure utility, no async, no state. Uses `exchange_calendars` library (or manual hardcoded schedule if we want zero dependencies).

```python
class MarketCalendar:
    """Market hours lookup per exchange."""

    def __init__(self, exchange: Exchange, timezone_override: str | None = None):
        ...

    def is_market_open(self, dt: datetime | None = None) -> bool:
        """Check if market is open at the given time (default: now)."""

    def next_open(self, dt: datetime | None = None) -> datetime:
        """Return the next market open time."""

    def next_close(self, dt: datetime | None = None) -> datetime:
        """Return the next market close time."""

    def minutes_until_close(self, dt: datetime | None = None) -> float | None:
        """Minutes until market close. None if market is closed."""

    def should_liquidate(self, minutes_before_close: int = 15) -> bool:
        """True if market closes within `minutes_before_close` minutes."""
```

**Exchange rules (hardcoded initially, can add library later):**

| Exchange | Hours | Timezone | Holidays |
|----------|-------|----------|----------|
| Binance | 24/7 | N/A | None |
| Alpaca | 9:30–16:00 | US/Eastern | NYSE holidays (hardcode major ones, fetch rest from Alpaca API) |

**`is_market_open()` for Binance:** Always returns `True`.

**Holiday handling:** Start with hardcoded 2026 NYSE holidays. Later can fetch from Alpaca calendar API (`GET /v2/calendar`).

### Step 2: Config (no DB migration needed)

**Schedule mode stored in `data_config` JSON** (already a Text column on TradingSession):
```json
{
  "resolution": "1min",
  "exec_every_n": 1,
  "schedule_mode": "always_on",
  "fields": { ... }
}
```
Values: `"always_on"`, `"market_hours"`, `"market_hours_liquidate"`.
Default: `"always_on"` (existing sessions are unaffected — absence means always_on).

**`config/default.yaml` — Add:**
```yaml
calendar:
  liquidate_minutes_before_close: 5
  pre_market_start_minutes: 0       # future: allow pre-market trading
  post_market_end_minutes: 0        # future: allow after-hours
```

**`session/manager.py` `DEFAULT_DATA_CONFIG` — Add default:**
```python
DEFAULT_DATA_CONFIG = {
    "resolution": "1min",
    "exec_every_n": 1,
    "schedule_mode": "always_on",
    "fields": { ... },
    ...
}
```

### Step 3: DataCollector Integration

**`data/collector.py` — Modify `_collection_loop()`:**

Current (line 304):
```python
while self._running:
    await self._collect_once()
    ...
```

New:
```python
while self._running:
    if self._calendar and not self._calendar.is_market_open():
        next_open = self._calendar.next_open()
        sleep_seconds = (next_open - datetime.now(timezone.utc)).total_seconds()
        sleep_seconds = max(sleep_seconds, 60)  # check at least every 60s
        sleep_seconds = min(sleep_seconds, 300)  # don't sleep more than 5 min at a time
        logger.info("Market closed, sleeping %.0fs until %s", sleep_seconds, next_open)
        await asyncio.sleep(sleep_seconds)
        continue
    await self._collect_once()
    ...
```

**Constructor change:**
```python
def __init__(self, ..., calendar: MarketCalendar | None = None):
    self._calendar = calendar
```

### Step 4: SessionScheduler in SessionManager

**`session/manager.py` — Add `_schedule_loop()` background task:**

Started in `_start_pipeline()` alongside collector/router/portfolio tasks.

```python
async def _schedule_loop(self, pipeline: SessionPipeline, config: dict) -> None:
    """Monitor market calendar and trigger actions."""
    calendar = pipeline.calendar  # MarketCalendar instance
    schedule_mode = pipeline.schedule_mode
    liquidate_minutes = config.get("calendar", {}).get("liquidate_minutes_before_close", 15)

    if schedule_mode == "always_on":
        return  # nothing to do

    while pipeline.running:
        if schedule_mode == "market_hours_liquidate":
            if calendar.should_liquidate(liquidate_minutes):
                # Flatten all positions by setting zero weights
                await self._liquidate_session(pipeline)
                # Wait until market actually closes, then enter sleep mode
                close_time = calendar.next_close()
                sleep_for = (close_time - datetime.now(timezone.utc)).total_seconds() + 60
                await asyncio.sleep(max(sleep_for, 60))
                continue

        await asyncio.sleep(30)  # check every 30 seconds
```

**`_liquidate_session()`** — Publishes zero-weight rebalance:
```python
async def _liquidate_session(self, pipeline: SessionPipeline) -> None:
    """Force-rebalance to zero weights (flatten all positions)."""
    weights = np.zeros(len(pipeline.executor.symbols))
    # ... same flow as _run_strategy_cycle but with zero weights
```

### Step 5: SessionPipeline Changes

Add fields:
```python
class SessionPipeline:
    def __init__(self, session_id, session_type, schedule_mode="always_on"):
        ...
        self.schedule_mode = schedule_mode
        self.calendar: MarketCalendar | None = None
```

### Step 6: API + UI

**UI: Data Config tab (editor page)**
The schedule mode toggle lives on the **Data Config tab** alongside resolution and lookback settings — it's part of "when does data collection + strategy execution happen."

- Add a `schedule_mode` dropdown/toggle to the Data Config section: `Always On` / `Market Hours (Hold Overnight)` / `Market Hours (Liquidate at Close)`
- Default: `always_on` for Binance sessions, `market_hours` for Alpaca sessions
- Stored as part of `data_config` JSON (not a separate DB column) — avoids schema migration

**`monitoring/editor.py`:**
- `load_editor_data` already returns `data_config` — schedule_mode will be included automatically
- `deploy` already saves `data_config` to DB — no extra endpoint needed

**`monitoring/sessions.py`:**
- Add `GET /api/sessions/{id}/market-status` — returns `{open: bool, next_open: str, next_close: str, minutes_to_close: float}`

**`session/manager.py` `update_session()`:**
- Already handles `data_config` updates (BUG-19 fix) — schedule_mode flows through automatically

### Step 7: Backtest Integration

**`backtest/engine.py`:**
- When processing daily bars, skip weekends and holidays (already handled by yfinance — it doesn't return weekend data)
- For intraday backtests, filter bars outside market hours
- No rebalance on bars outside market hours when `schedule_mode != "always_on"`

---

## File Changes Summary

| File | Change |
|------|--------|
| `shared/market_calendar.py` | **NEW** — MarketCalendar class |
| `config/default.yaml` | Add `calendar:` section |
| `data/collector.py` | Add calendar check in `_collection_loop()`, accept calendar in constructor |
| `session/manager.py` | Add `_schedule_loop()`, `_liquidate_session()`, pass calendar to collector, read `schedule_mode` from `data_config`, update `DEFAULT_DATA_CONFIG` |
| `monitoring/sessions.py` | Add `GET /api/sessions/{id}/market-status` endpoint |
| `backtest/engine.py` | Skip non-market bars for intraday backtests |

**No DB migration needed** — `schedule_mode` lives in existing `data_config` JSON column.
**No `db/models.py` change** — no new columns.
**UI lives on Data Config tab** — `schedule_mode` field in data_config JSON, handled by existing editor deploy flow.

---

## Dependencies

- `exchange_calendars` pip package (optional — can hardcode initially)
- `pytz` or `zoneinfo` for timezone handling (stdlib `zoneinfo` preferred, Python 3.9+)

---

## Testing Plan

1. **Unit test `MarketCalendar`:** Test `is_market_open()` at known times (weekday 10am ET = open, Saturday = closed, holiday = closed)
2. **Unit test Binance calendar:** Always returns open
3. **Integration test:** Start an Alpaca sim session with `market_hours` mode on a weekend — verify collector doesn't scrape
4. **Liquidation test:** Mock calendar to return `should_liquidate=True`, verify zero-weight rebalance fires
