"""Entry point: Execution service (risk manager + order router + portfolio tracker)."""

import asyncio
import signal

from shared.config import load_config
from shared.redis_client import create_redis_client
from monitoring.logger import setup_logging
from db.session import init_engine, init_db, close_db
from risk.manager import RiskManager
from execution.router import OrderRouter
from portfolio.tracker import PortfolioTracker
from portfolio.reconciler import Reconciler


async def main():
    config = load_config()
    setup_logging(config)

    # Initialize DB
    init_engine(config)
    await init_db()

    # Initialize Redis
    redis = create_redis_client(config)
    await redis.connect()

    # Create services
    risk_mgr = RiskManager(config, redis)
    router = OrderRouter(config, redis)
    tracker = PortfolioTracker(config, redis)
    reconciler = Reconciler(config, redis)

    # Graceful shutdown
    shutdown_event = asyncio.Event()

    def handle_signal():
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)

    # Run all services concurrently
    tasks = [
        asyncio.create_task(risk_mgr.start(), name="risk_manager"),
        asyncio.create_task(router.start(), name="order_router"),
        asyncio.create_task(tracker.start(), name="portfolio_tracker"),
        asyncio.create_task(reconciler.start(), name="reconciler"),
    ]

    # Wait for shutdown signal
    await shutdown_event.wait()

    # Stop services
    await risk_mgr.stop()
    await router.stop()
    await tracker.stop()
    await reconciler.stop()

    for task in tasks:
        task.cancel()

    await redis.disconnect()
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
