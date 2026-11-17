# Trading — Private AI Trading System

A research-first, risk-controlled trading system for MetaTrader 5. The first deployment is private and single-account; the architecture is intentionally separated so it can later support multiple isolated users and subscription plans.

> **Safety status: research / simulation only.** This repository does not currently place live orders. Do not connect a funded account or add broker credentials until the execution adapter, operational safeguards, and demo validation have been independently reviewed.

## Principles

- Protect capital before optimizing returns.
- No profit guarantees or target-return promises.
- AI may explain or rank evidence; deterministic, tested code owns risk decisions.
- Strategies must demonstrate out-of-sample robustness after spread, commission, swaps, and slippage.
- Never blindly retry an order whose execution outcome is unknown.
- Keep broker credentials and API keys out of source control.
- Every meaningful change requires tests and a reviewable commit.

## Initial technology choices

- Python 3.12+ for the research and application core.
- MetaTrader 5 integration isolated behind an adapter and initially run on Windows.
- Railway is reserved for suitable control-plane services (for example, Telegram interface and PostgreSQL); it is not the MT5 terminal host.
- Telegram is an interface, not the authority for risk or execution.
- OpenAI API integration is optional and must not be on the critical path for order safety.

## Repository layout

```
src/trading/
  risk/          deterministic risk policy
tests/            offline unit tests
docs/             architecture, safety, and validation decisions
```

The repository starts with a small, executable risk-policy foundation. Broker connectivity, strategies, AI, persistence, and deployment are intentionally not added until their interfaces and tests are specified.

## Development

Create an environment and install development dependencies:

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
ruff check .
mypy src
```

## Current milestone

**Milestone 0 — safe foundation:** repository conventions, architecture notes, deterministic risk gate, and offline tests. No live trading functionality is present.
