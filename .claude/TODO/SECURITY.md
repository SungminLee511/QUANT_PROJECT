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

---
