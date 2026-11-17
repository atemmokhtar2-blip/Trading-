# Railway deployment plan

## Target

The complete application runs in Railway. There is no local desktop terminal, Windows host, or separately managed trading machine.

## Railway project services

| Service | Responsibility | Initial runtime mode |
|---|---|---|
| `bot` | Telegram webhook/polling, user commands, operator controls, status | Long-running Python service |
| `trading-worker` | Market-data ingestion, strategy loop, risk checks, paper execution, reconciliation | Separate long-running Python worker |
| `PostgreSQL` | Durable users/configuration, strategy runs, audit trail, portfolio and execution state | Railway managed database |

The bot and worker use the same repository with separate Railway services and start commands. Configure the bot service start command as `python -m trading.app.bot` and the worker service as `python -m trading.app.worker`. Attach the Neon connection string to both as `DATABASE_URL`. The bot also needs `TELEGRAM_BOT_TOKEN` and `ADMIN_TELEGRAM_ID`. Set `TRADING_MODE=paper` on both. Set the worker replica count to exactly one for this scaffold.

## Worker ownership and restart safety

- Only one worker may own an account/strategy execution stream at a time.
- Use a PostgreSQL-backed lease/lock with an owner ID, expiry, and heartbeat. A process must stop placing new orders if it loses the lease.
- Persist intent and state transitions before external side effects.
- On restart, reconcile pending intents and exchange state before processing new signals.
- Graceful shutdown stops new decisions, closes data subscriptions, and leaves enough durable state for safe recovery.
- Telegram handlers must not directly submit exchange orders or bypass the worker/risk boundary.

## Environment configuration

Non-secret configuration should explicitly identify the runtime mode, for example:
- `APP_ENV`
- `TRADING_MODE` (initially `paper`)
- `DATABASE_URL`
- `TELEGRAM_BOT_TOKEN`
- `ADMIN_TELEGRAM_ID`
- `INITIAL_PAPER_BALANCE` (display/configuration placeholder; default `1000`)
- Binance market-data base URL / WebSocket configuration (public endpoints only in the initial phase)

Later, the Testnet adapter may add dedicated Testnet API key/secret variables. These must be stored only as Railway secrets. Production credentials and live trading mode are rejected by the initial configuration. Never print environment values, credentials, signed request URLs, or authorization headers in logs.

## Deployment and operational gates

1. Build and run the full offline test suite in CI.
2. Deploy the bot and worker to a Railway staging environment with `TRADING_MODE=paper`.
3. Verify database migrations, health/readiness checks, logs, graceful shutdown, and restart recovery.
4. Verify that two worker instances cannot both acquire the same execution lease.
5. Verify the kill switch and that Telegram/API outages cannot bypass risk checks.
6. Verify public Binance market-data reconnect, stale-data rejection, and rate-limit handling.
7. Only after the simulator is validated, add Binance Spot Testnet credentials and authenticated Testnet execution as a separate reviewed milestone.

## Current implementation limits

The Telegram polling bot and idempotent initial PostgreSQL schema are scaffolded. The worker currently writes a 30-second heartbeat only: it does not yet ingest Binance prices, run a strategy, create paper fills, or persist the in-memory ledger. There is no distributed worker lease yet, so run exactly one worker replica. The bot's pause/resume buttons change the database control flag but do not yet control an active strategy loop. Do not interpret a healthy bot/worker process as an active trading system. Binance API keys are not consumed; public market data will not need them. Testnet credentials and order execution are not implemented.
