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
- Railway hosts the complete application: Telegram interface, trading worker, PostgreSQL, and operational health checks.
- Binance market data and exchange APIs are accessed over HTTPS/WebSocket from Railway; no desktop terminal or Windows host is required.
- Public market data does not require API credentials. Testnet credentials will only be introduced when the isolated Testnet adapter is implemented.
- Telegram is an interface, not the authority for risk or execution.
- OpenAI API integration is optional and must not be on the critical path for order safety.

## Railway service layout

- **bot service:** Telegram updates, user commands, status, and operator controls.
- **trading worker:** market-data ingestion, strategy scheduling, risk checks, paper execution, and reconciliation tasks. It must enforce single-owner execution/leader locking.
- **PostgreSQL:** durable configuration, run metadata, audit events, and portfolio state.
- Both application services are deployed from this repository and configured with separate Railway start commands and environment variables. The database is provisioned inside the same Railway project.

The initial paper-trading milestone does not need Binance API keys. Secrets are added only for a later Testnet stage and are stored as Railway variables, never committed.

## Repository layout

```
src/trading/
  risk/          deterministic risk policy
  portfolio/     decimal-based portfolio ledger
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

**Milestone 1 — paper-trading foundation:** deterministic risk policy and virtual portfolio ledger. The next implementation steps are the paper execution engine, validated market-data contracts, and deterministic replay. Binance connectivity, Railway deployment manifests, and live trading are not considered complete until separately implemented and tested.
