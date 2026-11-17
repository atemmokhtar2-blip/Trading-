# Railway deployment plan

## Target

The complete application runs in Railway. There is no local desktop terminal, Windows host, or separately managed trading machine.

## Railway project services

| Service | Responsibility | Initial runtime mode |
|---|---|---|
| `bot` | Telegram webhook/polling, user commands, operator controls, status | Long-running Python service |
| `trading-worker` | Market-data ingestion, strategy loop, risk checks, paper execution, reconciliation | Separate long-running Python worker |
| `PostgreSQL` | Durable users/configuration, strategy runs, audit trail, portfolio and execution state | Railway managed database |

The bot and worker may use the same repository/image but must have separate start commands and independent health checks. The actual commands will be added only after their application entry points exist; do not deploy placeholder commands that appear healthy but do no work.

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
- `TELEGRAM_BOT_TOKEN` (only when Telegram integration is implemented)
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

## Current limitation

This repository currently contains the deterministic risk policy and in-memory portfolio ledger, not the Telegram bot, worker entry points, database persistence, or Railway service commands. Therefore this document records the deployment target and acceptance gates; it does not claim that a Railway deployment is already running.
