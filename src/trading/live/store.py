"""Persistence for the paper-trading loop: PostgreSQL and an in-memory twin for tests."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from trading.portfolio.ledger import Fill, FillSide, LedgerSnapshot


@dataclass(frozen=True, slots=True)
class StoredFill:
    fill: Fill
    reason: str
    filled_at: datetime


@dataclass(frozen=True, slots=True)
class EquityPoint:
    recorded_at: datetime
    equity: Decimal
    cash: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_fees: Decimal


class PaperStore(Protocol):
    async def record_fill(self, item: StoredFill) -> None: ...
    async def load_fills(self) -> list[StoredFill]: ...
    async def save_bracket(
        self, symbol: str, stop: Decimal, target: Decimal | None
    ) -> None: ...
    async def delete_bracket(self, symbol: str) -> None: ...
    async def load_brackets(self) -> dict[str, tuple[Decimal, Decimal | None]]: ...
    async def record_equity(self, at: datetime, snapshot: LedgerSnapshot) -> None: ...


class InMemoryPaperStore:
    def __init__(self) -> None:
        self.fills: list[StoredFill] = []
        self.brackets: dict[str, tuple[Decimal, Decimal | None]] = {}
        self.equity: list[EquityPoint] = []

    async def record_fill(self, item: StoredFill) -> None:
        if all(existing.fill.fill_id != item.fill.fill_id for existing in self.fills):
            self.fills.append(item)

    async def load_fills(self) -> list[StoredFill]:
        return sorted(self.fills, key=lambda item: item.fill.fill_id)

    async def save_bracket(self, symbol: str, stop: Decimal, target: Decimal | None) -> None:
        self.brackets[symbol] = (stop, target)

    async def delete_bracket(self, symbol: str) -> None:
        self.brackets.pop(symbol, None)

    async def load_brackets(self) -> dict[str, tuple[Decimal, Decimal | None]]:
        return dict(self.brackets)

    async def record_equity(self, at: datetime, snapshot: LedgerSnapshot) -> None:
        self.equity.append(
            EquityPoint(at, snapshot.equity, snapshot.cash, snapshot.realized_pnl,
                        snapshot.unrealized_pnl, snapshot.total_fees)
        )


class PostgresPaperStore:
    """asyncpg-backed store; `pool` is an asyncpg.Pool (typed Any: no stubs installed)."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def record_fill(self, item: StoredFill) -> None:
        fill = item.fill
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO paper_trade_log
                   (fill_id, symbol, side, quantity, price, fee, reason, filled_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT (fill_id) DO NOTHING""",
                fill.fill_id, fill.instrument, fill.side.value, fill.quantity,
                fill.price, fill.fee, item.reason, item.filled_at,
            )

    async def load_fills(self) -> list[StoredFill]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM paper_trade_log ORDER BY fill_id ASC"
            )
        return [
            StoredFill(
                Fill(
                    fill_id=row["fill_id"],
                    instrument=row["symbol"],
                    side=FillSide(row["side"]),
                    quantity=row["quantity"],
                    price=row["price"],
                    fee=row["fee"],
                ),
                row["reason"],
                row["filled_at"],
            )
            for row in rows
        ]

    async def save_bracket(self, symbol: str, stop: Decimal, target: Decimal | None) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO paper_brackets (symbol, stop_price, target_price, updated_at)
                   VALUES ($1,$2,$3,now()) ON CONFLICT (symbol) DO UPDATE SET
                   stop_price=EXCLUDED.stop_price, target_price=EXCLUDED.target_price,
                   updated_at=now()""",
                symbol, stop, target,
            )

    async def delete_bracket(self, symbol: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM paper_brackets WHERE symbol=$1", symbol)

    async def load_brackets(self) -> dict[str, tuple[Decimal, Decimal | None]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT symbol, stop_price, target_price FROM paper_brackets")
        return {row["symbol"]: (row["stop_price"], row["target_price"]) for row in rows}

    async def record_equity(self, at: datetime, snapshot: LedgerSnapshot) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO paper_equity
                   (recorded_at, equity, cash, realized_pnl, unrealized_pnl, total_fees)
                   VALUES ($1,$2,$3,$4,$5,$6)""",
                at, snapshot.equity, snapshot.cash, snapshot.realized_pnl,
                snapshot.unrealized_pnl, snapshot.total_fees,
            )

    async def summary(self, recent: int = 5) -> dict[str, Any]:
        """Latest equity point, peak equity, trade count and the most recent fills."""
        async with self._pool.acquire() as conn:
            latest = await conn.fetchrow(
                "SELECT * FROM paper_equity ORDER BY recorded_at DESC, id DESC LIMIT 1"
            )
            peak = await conn.fetchval("SELECT max(equity) FROM paper_equity")
            count = await conn.fetchval("SELECT count(*) FROM paper_trade_log")
            fills = await conn.fetch(
                "SELECT symbol, side, quantity, price, reason, filled_at "
                "FROM paper_trade_log ORDER BY filled_at DESC, fill_id DESC LIMIT $1",
                recent,
            )
            brackets = await conn.fetch("SELECT symbol FROM paper_brackets ORDER BY symbol")
        return {
            "latest": dict(latest) if latest else None,
            "peak_equity": peak,
            "fill_count": int(count or 0),
            "recent_fills": [dict(row) for row in fills],
            "open_symbols": [row["symbol"] for row in brackets],
        }
