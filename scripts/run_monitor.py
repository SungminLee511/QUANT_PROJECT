"""Entry point: Monitoring service (dashboard + Telegram bot)."""

import asyncio
import signal

from shared.config import load_config
from shared.redis_client import create_redis_client
from monitoring.logger import setup_logging
from db.session import init_engine, init_db, close_db
from monitoring.dashboard import run_dashboard
from monitoring.telegram_bot import TelegramAlertBot


async def main():
    config = load_config()
    setup_logging(config)

    # Initialize DB (for reading orders/equity history)
    init_engine(config)
    await init_db()

    # Initialize Redis
    redis = create_redis_client(config)
    await redis.connect()

    # Start Telegram bot
    tg_bot = TelegramAlertBot(config, redis)

    tasks = [
        asyncio.create_task(run_dashboard(config, redis), name="dashboard"),
        asyncio.create_task(tg_bot.start(), name="telegram_bot"),
    ]

    # Graceful shutdown
    shutdown_event = asyncio.Event()

    def handle_signal():
        shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)

    await shutdown_event.wait()

    await tg_bot.stop()
    for task in tasks:
        task.cancel()

    await redis.disconnect()
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
