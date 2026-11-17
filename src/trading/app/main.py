from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from contextlib import suppress

from aiogram import Bot

from trading.app.bot import build_dispatcher
from trading.app.config import Settings
from trading.app.database import Database

logger = logging.getLogger(__name__)


async def run_paper_worker_heartbeat(
    db: Database, instance_id: str, interval_seconds: int = 30
) -> None:
    """Keep a heartbeat for the scaffold worker; this is not a trading loop."""
    while True:
        async with db.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO worker_heartbeat(worker_name, instance_id, heartbeat_at)
                   VALUES('paper-worker', $1, now())
                   ON CONFLICT(worker_name) DO UPDATE SET
                   instance_id=EXCLUDED.instance_id, heartbeat_at=now()""",
                instance_id,
            )
        await asyncio.sleep(interval_seconds)


async def main() -> None:
    settings = Settings.from_env(require_telegram=True)
    if settings.telegram_bot_token is None or settings.admin_telegram_id is None:
        raise RuntimeError("Telegram configuration validation unexpectedly failed")

    db = await Database.connect(settings.database_url)
    bot = Bot(token=settings.telegram_bot_token)
    dispatcher = build_dispatcher(db, settings)
    instance_id = f"{socket.gethostname()}-{uuid.uuid4()}"

    logger.info(
        "Single Railway service starting in %s mode; instance=%s",
        settings.trading_mode,
        instance_id,
    )
    try:
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(
                run_paper_worker_heartbeat(db, instance_id),
                name="paper-worker-heartbeat",
            )
            tasks.create_task(
                dispatcher.start_polling(
                    bot, allowed_updates=dispatcher.resolve_used_update_types()
                ),
                name="telegram-polling",
            )
    finally:
        with suppress(Exception):
            await bot.session.close()
        await db.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(main())
