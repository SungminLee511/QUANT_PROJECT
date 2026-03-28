"""Dev helper: runs all services in a single process via asyncio.gather()."""

import asyncio
import signal

import uvicorn

from shared.config import load_config
from monitoring.logger import setup_logging
from monitoring.app import create_app


async def run_web(config):
    app = create_app(config)
    dash_cfg = config.get("monitoring", {}).get("dashboard", {})
    host = dash_cfg.get("host", "0.0.0.0")
    port = dash_cfg.get("port", 8080)
    server_config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(server_config)
    await server.serve()


async def main():
    config = load_config()
    setup_logging(config)

    # create_app() handles DB init, Redis, and SessionManager via its lifespan.
    # No need to initialise them here — that caused double-initialisation.
    tasks = [
        asyncio.create_task(run_web(config), name="web"),
    ]

    shutdown_event = asyncio.Event()

    def handle_signal():
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)

    print("All services started. Press Ctrl+C to stop.")
    await shutdown_event.wait()

    for task in tasks:
        task.cancel()

    # R5-5: Await cancelled tasks so cleanup handlers run and resources are freed
    await asyncio.gather(*tasks, return_exceptions=True)

    print("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
