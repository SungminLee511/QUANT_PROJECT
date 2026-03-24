"""Entry point: Web UI service (dashboard + strategy editor + session manager).

This is the main entry point that also orchestrates trading sessions.
Previously active sessions are auto-restarted on startup via the FastAPI lifespan.
"""

import asyncio
import signal

import uvicorn

from shared.config import load_config
from shared.redis_client import create_redis_client
from monitoring.logger import setup_logging
from db.session import init_engine, init_db, close_db
from monitoring.app import create_app
from session.manager import SessionManager


async def main():
    config = load_config()
    setup_logging(config)

    # Initialize DB
    init_engine(config)
    await init_db()

    # Initialize Redis
    redis = create_redis_client(config)
    await redis.connect()

    # Create session manager (orchestrates all trading pipelines)
    session_manager = SessionManager(config, redis)

    # Create FastAPI app (lifespan handles auto-restart of active sessions)
    app = create_app(config, redis, session_manager)
    dash_cfg = config.get("monitoring", {}).get("dashboard", {})
    host = dash_cfg.get("host", "0.0.0.0")
    port = dash_cfg.get("port", 8080)

    server_config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(server_config)

    # Graceful shutdown
    shutdown_event = asyncio.Event()

    def handle_signal():
        shutdown_event.set()
        server.should_exit = True

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)

    await server.serve()

    # Cleanup
    await session_manager.stop_all()
    await redis.disconnect()
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
