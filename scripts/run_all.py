"""Dev helper: runs all services in a single process via asyncio.gather()."""

import asyncio
import signal

from shared.config import load_config
from shared.redis_client import create_redis_client
from monitoring.logger import setup_logging
from db.session import init_engine, init_db, close_db
from data.manager import DataFeedManager
from strategy.engine import StrategyEngine
from risk.manager import RiskManager
from execution.router import OrderRouter
from portfolio.tracker import PortfolioTracker
from monitoring.dashboard import run_dashboard
from monitoring.telegram_bot import TelegramAlertBot


async def main():
    config = load_config()
    setup_logging(config)

    # Initialize DB
    init_engine(config)
    await init_db()

    # Initialize Redis
    redis = create_redis_client(config)
    await redis.connect()

    # Create all services
    data_mgr = DataFeedManager(config)
    strategy_engine = StrategyEngine(config, redis)
    risk_mgr = RiskManager(config, redis)
    router = OrderRouter(config, redis)
    tracker = PortfolioTracker(config, redis)
    tg_bot = TelegramAlertBot(config, redis)

    # Run everything
    tasks = [
        asyncio.create_task(data_mgr.run(), name="data"),
        asyncio.create_task(strategy_engine.start(), name="strategy"),
        asyncio.create_task(risk_mgr.start(), name="risk"),
        asyncio.create_task(router.start(), name="execution"),
        asyncio.create_task(tracker.start(), name="portfolio"),
        asyncio.create_task(run_dashboard(config, redis), name="dashboard"),
        asyncio.create_task(tg_bot.start(), name="telegram"),
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
    await strategy_engine.stop()
    await risk_mgr.stop()
    await router.stop()
    await tracker.stop()
    await tg_bot.stop()

    for task in tasks:
        task.cancel()

    await redis.disconnect()
    await close_db()
    print("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
