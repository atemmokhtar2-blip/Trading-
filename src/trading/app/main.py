from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from contextlib import suppress
from decimal import Decimal

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from trading.app.bot import build_dispatcher
from trading.app.config import Settings
from trading.app.database import Database
from trading.execution.paper import ExecutionCosts
from trading.live.loop import run_paper_loop
from trading.live.store import PostgresPaperStore
from trading.live.trader import PaperTrader
from trading.research.backtest import CostAssumptions
from trading.research.binance_public import BinancePublicClient

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


async def start_paper_loop(db: Database, bot: Bot, settings: Settings) -> None:
    """Build the paper trader (restoring saved state) and run the polling loop."""
    admin_id = settings.admin_telegram_id

    async def notify(text: str) -> None:
        if admin_id is not None:
            try:
                await bot.send_message(admin_id, text)
            except TelegramAPIError as exc:
                logger.warning("Paper alert not delivered: %s", type(exc).__name__)

    costs = CostAssumptions()
    try:
        trader = await PaperTrader.create(
            initial_cash=Decimal(settings.initial_paper_balance),
            store=PostgresPaperStore(db.pool),
            costs=ExecutionCosts(costs.spread_bps, costs.slippage_bps, costs.commission_bps),
            notify=notify,
        )
        await run_paper_loop(
            trader,
            BinancePublicClient(),
            db.is_paused,
            poll_seconds=settings.paper_poll_seconds,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        # A paper-loop fault must not take the Telegram control bot down with it.
        logger.exception("Paper trading loop stopped; Telegram bot keeps running")


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
            if settings.paper_loop_enabled:
                tasks.create_task(
                    start_paper_loop(db, bot, settings), name="paper-trading-loop"
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
