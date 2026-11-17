# Trading — Binance-First Automated Trading System

A research-first, risk-controlled trading system designed to run entirely on Railway. The first release is private, single-account, and simulation-first. Binance Spot is the initial exchange target; the core trading logic remains exchange-independent.

> **Safety status: research / simulation only.** The system does not currently place live orders. The initial deployment must use public market data and paper trading. Binance Spot Testnet integration is a later, separately tested stage. Live trading is disabled by default.

## Principles

- Protect capital before optimizing returns.
- No profit guarantees or target-return promises.
- AI may explain or rank evidence; deterministic, tested code owns risk decisions.
- Strategies must demonstrate out-of-sample robustness after realistic spread, commission, and slippage assumptions.
- Never blindly retry an order whose execution outcome is unknown.
- Keep exchange credentials and API secrets out of source control and logs.
- Every meaningful change requires tests and a reviewable commit.

## Initial technology and deployment choices

- Python 3.12+ for the research and application core.
- Binance Spot is the first exchange integration target. The first supported market set is USDT-quoted spot pairs; Futures, margin, leverage, and short selling are out of scope.
- Railway hosts the application process; Neon PostgreSQL provides the external durable database.
- Binance market data and exchange APIs are accessed over HTTPS/WebSocket from Railway; no desktop terminal or Windows host is required.
- Public market data does not require API credentials. Testnet credentials will only be introduced when the isolated Testnet adapter is implemented.
- Telegram is an interface, not the authority for risk or execution.
- OpenAI API integration is optional and must not be on the critical path for order safety.

## Railway deployment

The current scaffold is deployed as **one Railway service**. Start it with `python -m trading.app.main`; this starts Telegram polling and a lightweight paper-worker heartbeat concurrently in one process, sharing one Neon database pool. Keep the replica count at one until distributed worker ownership is implemented.

Set `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `ADMIN_TELEGRAM_ID`, and `TRADING_MODE=paper` in Railway Variables. The database is Neon, not a second Railway service.

Optional account-read integration: set `BINANCE_API_KEY` and `BINANCE_API_SECRET` together as Railway Variables. Create the Binance key with **Read Only** permission only. The authenticated adapter is restricted to signed `GET /api/v3/account`; it has no order, transfer, withdrawal, or account-changing methods. Public market-data collection continues to work without credentials. Never paste secrets into GitHub or chat, and never enable Spot Trading or withdrawals for this key.

## Repository layout

```
src/trading/
  risk/          deterministic risk policy
  portfolio/     decimal-based portfolio ledger
  execution/     deterministic paper execution engine
  app/           Telegram bot, PostgreSQL access, unified app entry point and heartbeat
migrations/       idempotent PostgreSQL schema
tests/            offline unit tests
docs/             architecture, safety, and validation decisions
```

## Development

Create an environment and install development dependencies:

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
ruff check .
mypy src
```

## Current milestone

**Milestone 2 — paper execution:** deterministic risk policy, virtual portfolio ledger, and next-bar paper execution with explicit spread/slippage/commission, risk gating, and conservative stop/target handling. Telegram control bot and PostgreSQL schema/connection are scaffolded on main. A single Railway process runs Telegram polling and a heartbeat task; the worker heartbeat does not ingest prices or trade. Next: add validated Binance public market data, deterministic strategy/replay, persist paper ledger events, then deploy and verify on Railway. Binance Testnet and live trading are not implemented.
