# Security — Open Issues

> Full audit: 2026-03-27. Personal-use system, not public-facing. Prioritize based on actual risk.

---

## CRITICAL

### SEC-3: XSS in logs.html — `source` and `symbol` not escaped

**File:** `monitoring/templates/logs.html` — Lines 89–93

`entry.source` and `entry.symbol` are injected directly into `innerHTML` without `escHtml()`. Only `entry.message` is escaped. A malicious log entry with `source='"><script>alert(1)</script>'` executes JS.

**Fix:** Apply `escHtml()` to all interpolated values, not just `message`.

---

## HIGH

### SEC-4: XSS in dashboard.html — symbol/side not escaped in table rendering

**File:** `monitoring/templates/dashboard.html` — Lines 148–162

`p.symbol`, `o.symbol`, `o.side` inserted via template literal into `innerHTML` without escaping. If backend returns malformed data, XSS executes.

**Fix:** Use `escHtml()` on all data fields in table `innerHTML`.

---

### ~~SEC-5: XSS via innerHTML in editor.html grid rendering~~ ✅ FIXED

**Fixed in:** commit (SEC-5). Added `escHtml()` helper. All user-controlled values in innerHTML (custom data name, lookback, source list, feedback lines) now escaped. CSS selector uses `CSS.escape()`.

---

### SEC-6: Missing session ownership validation on GET API endpoints

**File:** `monitoring/dashboard.py` — Lines 83–194

All `/api/*` endpoints accept `?session_id=` parameter. No validation that the session belongs to the authenticated user. Any authenticated user can read any session's data.

**Fix:** Validate `session_id` ownership in each endpoint (or add middleware).

---

### SEC-7: Unsafe JSON deserialization in `/editor/api/deploy`

**File:** `monitoring/editor.py` — Lines 161–206

No validation that `custom_data_code` is a list or that items are dicts. `custom_data_code: "string"` causes type confusion. No payload size limits.

**Fix:** Validate types with `isinstance()` checks before processing.

---

## MEDIUM

### SEC-8: Missing input validation on login credentials

**File:** `monitoring/app.py` — Lines 193–208

No length/type validation on username/password. Arbitrarily large payloads accepted. No rate limiting on failed attempts.

**Fix:** Add length limits (100/256), type checks, and rate limiting.

---

### SEC-9: No Content-Security-Policy header

**File:** `monitoring/app.py` — No CSP middleware

Without CSP, inline JavaScript is unrestricted, amplifying XSS impact.

**Fix:** Add CSP middleware allowing only self + CDN scripts.

---

### SEC-10: Missing X-Frame-Options / clickjacking protection

**File:** `monitoring/app.py` — No frame protection

App can be embedded in iframes. Could allow clickjacking on trading buttons.

**Fix:** Add `X-Frame-Options: DENY` and `X-Content-Type-Options: nosniff` headers.

---

### SEC-11: Hardcoded DB credentials in versioned config

**File:** `config/default.yaml` — Lines 22, 25, 33

`password: "changeme"` in source. Personal-use acceptable but poor practice.

**Fix:** Use environment variables only; remove from YAML.

---

## LOW

### SEC-12: Session cookie SameSite should be "strict"

**File:** `monitoring/auth.py` — Line 57

`samesite="lax"` allows cookies on cross-site top-level navigations. "strict" is safer for personal-use trading system.

---

### SEC-13: No rate limiting on `/login` endpoint

**File:** `monitoring/app.py`

Rate limiter covers `/backtest/api/run` but not `/login`. Brute force possible.

**Fix:** Add login to rate limit rules (5 attempts per minute).

---

### SEC-14: No client-side code size limits on strategy submission

**File:** `monitoring/templates/backtest.html` — Line 275

Strategy code sent without size validation. Backend should enforce, but client-side guard adds defense-in-depth.

---

> Previous items: SEC-1/SEC-2 sandbox limitations — ACCEPTED (see `DONE.md`).
