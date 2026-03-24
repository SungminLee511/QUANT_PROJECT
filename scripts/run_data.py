"""Entry point: Data feed service."""

import asyncio

from shared.config import load_config
from monitoring.logger import setup_logging
from data.manager import DataFeedManager


async def main():
    config = load_config()
    setup_logging(config)
    manager = DataFeedManager(config)
    await manager.run()


if __name__ == "__main__":
    asyncio.run(main())
