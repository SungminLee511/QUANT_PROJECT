"""Entry point: Strategy engine service."""

import asyncio
import signal

from shared.config import load_config
from shared.redis_client import create_redis_client
from monitoring.logger import setup_logging
from strategy.engine import StrategyEngine


async def main():
    config = load_config()
    setup_logging(config)
    redis = create_redis_client(config)
    await redis.connect()

    engine = StrategyEngine(config, redis)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown(engine, redis)))

    try:
        await engine.start()
    except asyncio.CancelledError:
        pass


async def shutdown(engine, redis):
    await engine.stop()
    await redis.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
