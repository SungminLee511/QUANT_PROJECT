# Security — Open Issues

> Extracted from CODE_REVIEW.md (2026-03-25). This is a personal-use system, not public-facing. Prioritize based on actual risk exposure.

---

## SEC-1: Strategy `exec()` sandbox is bypassable — CRITICAL

**File:** `strategy/executor.py` (~line 42)

The sandbox restricts `__import__` but allows `numpy`, which exposes `numpy.os` and `numpy.__builtins__`. The `type` builtin also enables reconstruction of forbidden operations. Any user deploying strategy code can access the OS.

**Options:**
- RestrictedPython
- Subprocess isolation with seccomp
- Wasm runtime (e.g. wasmtime-py)
- Accept risk for personal use (only you deploy strategies)

---

## SEC-2: Custom data `exec()` has no sandbox at all — CRITICAL

**File:** `data/collector.py` (~line 175)

Custom data functions compiled with full builtins (no `__builtins__` restriction). AST validation is trivially bypassable.

**Fix:** Same options as SEC-1. Lower priority since custom data is intentionally allowed network access.

---

## SEC-3: Plaintext credentials in config — HIGH

**Files:** `config/default.yaml`, `monitoring/auth.py`

Default creds hardcoded, password compared via `==` (no hashing). API keys stored plaintext in DB.

**Fix (if needed):**
- Hash passwords with `bcrypt`
- Encrypt API keys at rest with a server-side key
- For personal use: acceptable risk

---

## SEC-4: Session cookie not `secure` — HIGH

**File:** `monitoring/auth.py` (~line 24)

Missing `secure=True` on `set_cookie()`. Cookie can be sent over HTTP.

**Fix:** Add `secure=True` when not in dev mode. Requires HTTPS (cloudflare tunnel provides this).

---

---

---

## SEC-7: Credential timing attack — LOW

**File:** `monitoring/auth.py` (~line 68)

Uses `==` for password comparison. Use `hmac.compare_digest()` instead.
