# Final Audit Round 6 — 2026-03-28

> Sixth comprehensive codebase audit. Only **real, verified bugs** — confirmed by reading the actual code. Previous rounds: `FINAL_AUDIT.md` (FAUDIT-1–23), `FINAL_AUDIT_R2.md` (R2-1–15), `FINAL_AUDIT_R3.md` (R3-1–13), `FINAL_AUDIT_R4.md` (R4-1–11), `FINAL_AUDIT_R5.md` (R5-1–6).

---

## MEDIUM

### R6-1: yfinance fallback `day_change_pct` computation — division by zero produces `inf`

**File:** `data/sources/yfinance_source.py` line 362
**Code:**
```python
pct = np.diff(series) / series[:-1] * 100
```
**Problem:** The primary day_change_pct path (lines 335–340) correctly guards against zero denominators with `prev_val != 0`. However, the **fallback** path (lines 343–366), which triggers when close data wasn't co-requested with `day_change_pct`, uses vectorized `np.diff(series) / series[:-1]` with NO zero guard. If any bar in the historical close series has a price of `0.0` (data anomaly, adjusted data edge case, or delisted stock), the division produces `inf` values that silently propagate into the returned array.

**Impact:** `inf` values in `day_change_pct` corrupt downstream strategy calculations — any normalization, weighting, or comparison involving `inf` produces garbage results. The bug is silent (no exception raised).

**Fix:** Replace the vectorized division with a guarded version:
```python
with np.errstate(divide='ignore', invalid='ignore'):
    pct = np.where(series[:-1] != 0, np.diff(series) / series[:-1] * 100, np.nan)
```

---

### R6-2: `dashboard.html` missing `CSS.escape()` in querySelector — inconsistent with other templates

**File:** `monitoring/templates/dashboard.html` line 106
**Code:**
```javascript
const item = document.querySelector(`.session-item[data-id="${currentSessionId}"] .s-name`);
```
**Problem:** `currentSessionId` is interpolated into a CSS selector string without `CSS.escape()`. The R4-11 fix added `CSS.escape()` to `editor.html` (line 686, 866) and `logs.html` (line 154), but `dashboard.html` was missed. If `currentSessionId` contains CSS selector metacharacters (`]`, `"`, `\`, etc.), the querySelector can malfunction or be exploited for DOM injection.

**Impact:** In practice, session IDs are server-generated UUIDs, so exploitation is unlikely. But this breaks the defense-in-depth pattern established by R4-11 and is a consistency bug.

**Fix:** Change to:
```javascript
const item = document.querySelector(`.session-item[data-id="${CSS.escape(currentSessionId)}"] .s-name`);
```

---

### R6-3: Session manager `start_session`/`stop_session` race condition — await gap between duplicate-check and pipeline registration

**File:** `session/manager.py` lines 251–296 (start) and 344–381 (stop)
**Problem:** `start_session()` checks if a session is already running at line 253, but the check is separated from the pipeline registration (line 296) by an `await` at line 257 (`get_session_info`). In asyncio's cooperative model, another coroutine can run during that `await`, creating two race windows:

**Race 1 — Duplicate start:**
1. Coroutine A: `start_session("X")` passes check at line 253 (not in dict)
2. Coroutine A: yields at `await get_session_info(...)` (line 257)
3. Coroutine B: `start_session("X")` passes the SAME check (still not in dict)
4. Both create separate `SessionPipeline` objects; B overwrites A's pipeline at line 296
5. A's pipeline tasks become orphaned — running but unreachable

**Race 2 — Stop during start:**
1. `start_session("X")` adds pipeline to dict at line 296 (running=False, tasks=[])
2. Yields at `await ks.restore_from_db()` (line 302) or inside `_start_pipeline`
3. `stop_session("X")` finds the pipeline, cancels 0 tasks, removes from dict
4. `_start_pipeline` resumes, creates tasks, sets running=True on an orphaned pipeline
5. Tasks run indefinitely with no way to stop them

**Impact:** Rapid double-click on "Start Session" or programmatic concurrent API calls can leak background tasks. The orphaned tasks consume resources (Redis subscriptions, DB connections, data polling) indefinitely.

**Fix:** Add an `asyncio.Lock` per session (or a global lock for start/stop operations) to serialize start/stop calls. Alternatively, use a `_starting` sentinel state:
```python
if session_id in self._pipelines:
    return True  # Already running or being started
```

---

## Summary

| Severity | Count |
|----------|-------|
| HIGH | 0 |
| MEDIUM | 3 |
| LOW | 0 |
| **Total** | **3** |

---

## Rejected Findings (Verified Safe)

These were flagged by automated scan but confirmed NOT to be bugs:

| Claim | Why it's safe |
|-------|--------------|
| `editor.py` missing `db.commit()` | `get_session()` context manager auto-commits on normal exit (db/session.py:57) |
| CSRF wrapper passes old args | Python dict is mutated in-place via reference; `args[1]` points to same dict |
| SSE log queue race drops entries | Each client has its own queue; `_on_log_entry` fans out copies to all |
| SimAdapter no rollback on exception | `ValueError` raised before any state mutation (local vars only) |
| Router `_open_orders` dict race | asyncio cooperative model — dict ops between await points are atomic |
| `risk/limits.py` abs() on short positions | Conservative by design — total exposure check, not directional |
| SimAdapter quantity rescaling | Intentional partial-fill simulation behavior |
