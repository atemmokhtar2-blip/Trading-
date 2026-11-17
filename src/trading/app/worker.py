"""Backward-compatible entrypoint for older Railway start commands.

This module intentionally delegates to the unified app. Both Telegram polling
and the heartbeat therefore run in the same process and share one DB pool.
"""

import asyncio
import logging

from trading.app.main import main


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(main())
