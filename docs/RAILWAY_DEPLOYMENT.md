# Railway deployment

## One-service deployment (current scaffold)

Deploy exactly one Railway service from this repository. The single process starts:
- Telegram long-polling bot.
- A lightweight paper-worker heartbeat task.

Both tasks share one application process and one Neon PostgreSQL connection pool. Database migrations run at startup through `Database.connect()`.

### Railway settings

- Build command: `pip install .`
- Start command: `python -m trading.app.main`
- Replicas: **1**
- No separate worker service is needed for this release.

### Variables

Set these on the one Railway service:

| Variable | Value |
|---|---|
| `DATABASE_URL` | Neon PostgreSQL connection string |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `ADMIN_TELEGRAM_ID` | Your numeric Telegram user ID |
| `TRADING_MODE` | `paper` |
| `INITIAL_PAPER_BALANCE` | Optional; defaults to `1000` |

Use Railway's encrypted Variables interface. Never commit credentials or send them in chat. If Neon requires TLS, use its provided connection string with SSL enabled.

## Runtime safety

- Run one Railway replica only. Multiple replicas would start multiple Telegram pollers and duplicate worker heartbeats; distributed leader election is not implemented yet.
- Both concurrent tasks run inside one process and share the same database pool.
- If either the Telegram polling task or heartbeat task fails, the application task group shuts down the other task and the process exits so Railway can restart it.
- `TRADING_MODE` must be `paper`; every other mode is rejected at startup.
- Binance API keys are not read or used by this release. Public market-data ingestion is a later milestone and does not require private keys.

## What this release actually does

The bot registers users and provides admin status/pause/resume controls. The worker task only updates a 30-second heartbeat. There is no live market-data ingestion, no active strategy loop, no paper fills, and no persistent portfolio ledger yet. The pause/resume flag is stored in PostgreSQL but does not currently gate a trading loop because that loop does not exist.

A healthy Railway deployment therefore proves only that the bot, database connection, migrations, and heartbeat are running. It is not evidence of profitable signals or an operational trading bot.

## Next acceptance gates

1. Verify Telegram polling and Neon migrations in Railway logs.
2. Verify the heartbeat timestamp updates every 30 seconds.
3. Add Binance public market-data ingestion with stale-data and reconnect tests.
4. Add deterministic strategy evaluation and persist paper intents/fills.
5. Add restart-safe worker ownership before allowing more than one replica.
6. Validate the paper simulator with realistic fees, spread, slippage, and out-of-sample tests before considering Testnet.
