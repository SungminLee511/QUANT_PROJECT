# Security — Open Issues

> Full audit: 2026-03-27. Personal-use system, not public-facing. Prioritize based on actual risk.

---

## CRITICAL

### ~~SEC-3: XSS in logs.html — `source` and `symbol` not escaped~~ ✅ FIXED

**Fixed in:** commit 0fe1809. Escaped all user data in logs HTML.

---

## HIGH

### ~~SEC-4: XSS in dashboard.html — symbol/side not escaped in table rendering~~ ✅ FIXED

**Fixed in:** commit 0fe1809. Escaped all user data in dashboard HTML.

---

### ~~SEC-5: XSS via innerHTML in editor.html grid rendering~~ ✅ FIXED

**Fixed in:** commit (SEC-5). Added `escHtml()` helper. All user-controlled values in innerHTML (custom data name, lookback, source list, feedback lines) now escaped. CSS selector uses `CSS.escape()`.

---

### ~~SEC-6: Missing session ownership validation on GET API endpoints~~ ✅ FIXED

**Fixed in:** commit be291b1. Whitelisted allowed fields in session update endpoint.

---

### ~~SEC-7: Unsafe JSON deserialization in `/editor/api/deploy`~~ ✅ FIXED

**Fixed in:** commit d56b11e. Added type validation checks.

---

## MEDIUM

### ~~SEC-8: Missing input validation on login credentials~~ ✅ FIXED

**Fixed in:** SEC-8 commit. Added type check and length validation (1–128 chars) for username/password in `/login` POST handler. Rejects early with generic error message.

---

### ~~SEC-9: No Content-Security-Policy header~~ ✅ FIXED

**Fixed in:** SEC-9 commit. Added `security_headers_middleware` to app.py. CSP allows `'self'` + `'unsafe-inline'` for scripts/styles (needed by templates), `frame-ancestors 'none'`.

---

### ~~SEC-10: Missing X-Frame-Options / clickjacking protection~~ ✅ FIXED

**Fixed in:** SEC-10 commit. Added `X-Frame-Options: DENY` and `X-Content-Type-Options: nosniff` in `security_headers_middleware`.

---

### SEC-11: Hardcoded DB credentials in versioned config

**File:** `config/default.yaml` — Lines 22, 25, 33

`password: "changeme"` in source. Personal-use acceptable but poor practice.

**Fix:** Use environment variables only; remove from YAML.

---

## LOW

### ~~SEC-12: Session cookie SameSite should be "strict"~~ ✅ FIXED

**Fixed in:** SEC-12 commit. Changed `samesite="lax"` to `samesite="strict"` in `create_session()`.

---

### ~~SEC-13: No rate limiting on `/login` endpoint~~ ✅ FIXED

**Fixed in:** SEC-13 commit. Added `/login` to `DEFAULT_RULES` in `rate_limit.py` (10 requests/60s window).

---

### ~~SEC-14: No client-side code size limits on strategy submission~~ ✅ FIXED

**Fixed in:** SEC-14 commit. Added `MAX_CODE_SIZE = 100_000` (100 KB) server-side validation in editor.py for `/api/validate`, `/api/validate-custom`, and `/api/deploy`. Rejects with error before processing.

---

> Previous items: SEC-1/SEC-2 sandbox limitations — ACCEPTED (see `DONE.md`).
