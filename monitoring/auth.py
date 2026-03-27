"""Simple session-based authentication — cookie auth, in-memory sessions."""

import hmac
import secrets
import time
from functools import wraps

from fastapi import Request, Response
from fastapi.responses import RedirectResponse

SESSION_COOKIE = "qt_session"

# In-memory session store: {token: {"username": str, "created_at": float}}
_sessions: dict[str, dict] = {}
_last_cleanup: float = 0.0
_CLEANUP_INTERVAL: float = 300.0  # seconds between automatic cleanups


def cleanup_expired_sessions() -> int:
    """Remove all expired sessions. Returns number removed."""
    now = time.time()
    expired = [
        token for token, sess in _sessions.items()
        if now - sess["created_at"] > sess["ttl"]
    ]
    for token in expired:
        _sessions.pop(token, None)
    return len(expired)


def _maybe_cleanup() -> None:
    """Run cleanup at most once every _CLEANUP_INTERVAL seconds."""
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup > _CLEANUP_INTERVAL:
        _last_cleanup = now
        removed = cleanup_expired_sessions()
        if removed:
            import logging
            logging.getLogger(__name__).debug("Cleaned up %d expired auth sessions", removed)


def create_session(response: Response, username: str, ttl_hours: int = 24) -> str:
    """Create a new session and set the cookie."""
    token = secrets.token_urlsafe(32)
    _sessions[token] = {
        "username": username,
        "created_at": time.time(),
        "ttl": ttl_hours * 3600,
        "csrf_token": secrets.token_urlsafe(32),
    }
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",  # SEC-12: strict prevents CSRF via cross-site navigation
        max_age=ttl_hours * 3600,
    )
    return token


def get_current_user(request: Request) -> str | None:
    """Return the username from the session cookie, or None if not logged in."""
    _maybe_cleanup()
    token = request.cookies.get(SESSION_COOKIE)
    if not token or token not in _sessions:
        return None
    session = _sessions[token]
    # Check expiry
    if time.time() - session["created_at"] > session["ttl"]:
        _sessions.pop(token, None)
        return None
    return session["username"]


def destroy_session(request: Request, response: Response) -> None:
    """Log out — remove session and clear cookie."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        _sessions.pop(token, None)
    response.delete_cookie(SESSION_COOKIE)


def require_auth(request: Request) -> RedirectResponse | None:
    """If not authenticated, return a redirect to /login. Otherwise None."""
    user = get_current_user(request)
    if user is None:
        return RedirectResponse(url="/login", status_code=302)
    return None


def check_credentials(username: str, password: str, config: dict) -> bool:
    """Validate username/password against config."""
    auth_cfg = config.get("auth", {})
    expected_user = auth_cfg.get("username", "admin")
    expected_pass = auth_cfg.get("password", "admin1234")
    return (
        hmac.compare_digest(username, expected_user)
        and hmac.compare_digest(password, expected_pass)
    )


# ── CSRF Protection (ARCH-3) ──────────────────────────────────────────


def get_csrf_token(request: Request) -> str | None:
    """Return the CSRF token for the current authenticated session."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token or token not in _sessions:
        return None
    return _sessions[token].get("csrf_token")


def validate_csrf(request: Request) -> bool:
    """Validate CSRF token from X-CSRF-Token header against session.

    Returns True if valid, False if invalid or missing.
    Safe methods (GET, HEAD, OPTIONS) always pass.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return True

    expected = get_csrf_token(request)
    if not expected:
        return False

    provided = request.headers.get("X-CSRF-Token", "")
    if not provided:
        return False

    return hmac.compare_digest(provided, expected)
