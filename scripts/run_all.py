"""Dev helper: runs all services in a single process via asyncio.gather()."""

import asyncio
import signal

import uvicorn

from shared.config import load_config
from shared.redis_client import create_redis_client
from monitoring.logger import setup_logging
from db.session import init_engine, init_db, close_db
from monitoring.app import create_app
from session.manager import SessionManager


async def run_web(config, redis, session_manager):
    app = create_app(config, redis, session_manager)
    dash_cfg = config.get("monitoring", {}).get("dashboard", {})
    host = dash_cfg.get("host", "0.0.0.0")
    port = dash_cfg.get("port", 8080)
    server_config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(server_config)
    await server.serve()


async def main():
    config = load_config()
    setup_logging(config)

    # Initialize DB
    init_engine(config)
    await init_db()

    # Initialize Redis
    redis = create_redis_client(config)
    await redis.connect()

    # Create session manager
    session_manager = SessionManager(config, redis)

    # Run web server (session manager lives inside FastAPI's lifespan)
    tasks = [
        asyncio.create_task(run_web(config, redis, session_manager), name="web"),
    ]

    shutdown_event = asyncio.Event()

    def handle_signal():
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)

    print("All services started. Press Ctrl+C to stop.")
    await shutdown_event.wait()

    # Cleanup
    await session_manager.stop_all()

    for task in tasks:
        task.cancel()

    await redis.disconnect()
    await close_db()
    print("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
