"""Polling loop: public Binance candles -> PaperTrader. Never places real orders."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from trading.execution.paper import MarketBar
from trading.live.trader import PaperTrader

logger = logging.getLogger(__name__)

MAX_BACKOFF_SECONDS = 900


class MarketData(Protocol):
    def top_usdt_symbols(self, limit: int = 10) -> list[str]: ...
    def closed_klines(
        self, symbol: str, interval: str = "1h", limit: int = 1000
    ) -> list[MarketBar]: ...


async def run_paper_loop(
    trader: PaperTrader,
    client: MarketData,
    is_paused: Callable[[], Awaitable[bool]],
    *,
    interval: str = "1h",
    poll_seconds: int = 300,
    symbol_count: int = 10,
    candle_limit: int = 300,
    sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    max_cycles: int | None = None,
) -> None:
    """Run until cancelled (or max_cycles, used by tests). Errors back off, never crash."""
    symbols: list[str] = []
    failures = 0
    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        cycles += 1
        try:
            if not symbols:
                symbols = await asyncio.to_thread(client.top_usdt_symbols, symbol_count)
                logger.info("Paper loop universe: %s", ",".join(symbols))
            trader.set_entries_enabled(not await is_paused())
            processed = 0
            for symbol in symbols:
                bars = await asyncio.to_thread(
                    client.closed_klines, symbol, interval, candle_limit
                )
                processed += await trader.process_bars(symbol, bars)
            if processed:
                await trader.record_equity(datetime.now(UTC))
            failures = 0
            delay: float = poll_seconds
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failures += 1
            delay = min(poll_seconds * 2**min(failures, 5), MAX_BACKOFF_SECONDS)
            logger.warning(
                "Paper loop cycle failed (%s), attempt %d, retry in %ds",
                type(exc).__name__, failures, delay,
            )
        await sleep(delay)
