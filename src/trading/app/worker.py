from __future__ import annotations

import asyncio
import logging
import socket
import uuid

from trading.app.config import Settings
from trading.app.database import Database

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = Settings.from_env()
    db = await Database.connect(settings.database_url)
    instance_id = f"{socket.gethostname()}-{uuid.uuid4()}"
    logger.info("Paper worker started; trading mode=%s; instance=%s", settings.trading_mode, instance_id)
    try:
        while True:
            async with db.pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO worker_heartbeat(worker_name, instance_id, heartbeat_at)
                       VALUES('paper-worker', $1, now())
                       ON CONFLICT(worker_name) DO UPDATE SET instance_id=EXCLUDED.instance_id,
                       heartbeat_at=now()""",
                    instance_id,
                )
            await asyncio.sleep(30)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
