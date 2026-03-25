"""Entry point: Web UI service (dashboard + strategy editor + session manager).

This is the main entry point that also orchestrates trading sessions.
Previously active sessions are auto-restarted on startup via the FastAPI lifespan.

NOTE: DB and Redis initialization happen inside the FastAPI lifespan (not before
uvicorn starts) to avoid event-loop mismatch with asyncpg.
"""

import logging
import signal
import uvicorn

from shared.config import load_config
from monitoring.logger import setup_logging

logger = logging.getLogger(__name__)


def _register_signal_handlers():
    """Log signal receipt for visibility. Uvicorn handles actual shutdown."""
    for sig in (signal.SIGTERM, signal.SIGINT):
        original = signal.getsignal(sig)

        def handler(signum, frame, _orig=original):
            logger.info("Received %s — initiating graceful shutdown...", signal.Signals(signum).name)
            # Delegate to uvicorn's handler (or default)
            if callable(_orig) and _orig not in (signal.SIG_DFL, signal.SIG_IGN):
                _orig(signum, frame)

        signal.signal(sig, handler)


def main():
    config = load_config()
    setup_logging(config)
    _register_signal_handlers()

    # Store config in env-accessible place for the app factory
    # The actual async init (DB, Redis) happens in the FastAPI lifespan
    # to keep everything in uvicorn's event loop.
    import monitoring.app as app_module
    app_module._boot_config = config

    dash_cfg = config.get("monitoring", {}).get("dashboard", {})
    host = dash_cfg.get("host", "0.0.0.0")
    port = dash_cfg.get("port", 8080)

    uvicorn.run(
        "monitoring.app:build_app",
        factory=True,
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
