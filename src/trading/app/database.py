from __future__ import annotations

from pathlib import Path
from typing import Any

import asyncpg


class Database:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> Database:
        pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=5, command_timeout=15)
        db = cls(pool)
        await db.migrate()
        return db

    async def migrate(self) -> None:
        migrations = Path(__file__).resolve().parents[3] / "migrations"
        async with self.pool.acquire() as conn:
            for schema_path in sorted(migrations.glob("*.sql")):
                await conn.execute(schema_path.read_text(encoding="utf-8"))

    async def register_user(
        self, telegram_id: int, username: str | None, first_name: str | None
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO bot_users (telegram_id, username, first_name, last_seen_at)
                   VALUES ($1, $2, $3, now())
                   ON CONFLICT (telegram_id) DO UPDATE SET username=EXCLUDED.username,
                   first_name=EXCLUDED.first_name, last_seen_at=now()""",
                telegram_id, username, first_name,
            )

    async def is_paused(self) -> bool:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT entries_paused FROM app_control WHERE id=1")
            return bool(row["entries_paused"]) if row else True

    async def set_paused(self, paused: bool, actor_id: int) -> None:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE app_control SET entries_paused=$1, updated_at=now() WHERE id=1", paused
                )
                await conn.execute(
                    (
                        "INSERT INTO audit_events "
                        "(actor_telegram_id, event_type, payload) VALUES ($1,$2,$3::jsonb)"
                    ),
                    actor_id, "entries_paused" if paused else "entries_resumed",
                    '{"source":"telegram"}',
                )

    async def dashboard(self) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT c.entries_paused, c.trading_mode,
                   (SELECT count(*) FROM bot_users) AS users,
                   (SELECT count(*) FROM audit_events
                    WHERE created_at >= date_trunc('day', now())) AS events_today,
                   (SELECT heartbeat_at FROM worker_heartbeat
                    WHERE worker_name='paper-worker') AS worker_heartbeat
                   FROM app_control c WHERE c.id=1"""
            )
            return dict(row) if row else {}

    async def close(self) -> None:
        await self.pool.close()
