# Paper Execution Engine — Milestone 2

## Status

Implemented as an offline, deterministic paper executor. It does not connect to Binance, request credentials, or submit exchange orders.

## Contract

- Strategy output is a `TradeIntent`, not a fill or exchange order.
- An intent is accepted only when its decision timestamp exactly matches the latest completed bar for that instrument.
- A market entry or manual exit fills no earlier than the next bar's open.
- Spread, slippage, and commission are mandatory explicit `ExecutionCosts` inputs. Zero is permitted only when deliberately configured.
- BUY intents require a protective stop below the decision price; optional target must be above it.
- The actual next-bar entry price is checked again against stop and target before risk evaluation.
- The deterministic risk gate evaluates stop-loss exposure, estimated entry/exit commission, current equity, drawdown baselines, open positions, and the kill switch immediately before the simulated fill.
- The ledger remains the authority for cash and position accounting. Insufficient cash is a rejected intent, not a partial fill.
- Stops and targets are evaluated only on bars after entry. If both are touched in one bar, the stop wins.
- A gap below a stop fills from the bar open with adverse spread/slippage, not at the more favorable stop price.
- Target gap improvement is not assumed; a touched target fills at its target level less exit costs.
- Long-only; no margin, Futures, leverage, short selling, or partial fills.
- Identical intent retries are idempotent; conflicting reuse of an intent ID is rejected.
- Execution events are immutable and ordered. They are in-memory in this milestone; durable persistence is a later Railway/PostgreSQL milestone.

## Known simplifications

- OHLC bars cannot reveal intrabar path. The adverse stop-first rule is used for stop/target ambiguity.
- Liquidity, queue position, exchange filters, partial fills, funding, and commission-asset conversion are not modeled.
- Risk period baselines are initialized from portfolio equity when the engine is constructed. Durable daily/weekly/monthly reset policy is not implemented.
- The executor currently expects one serialized caller; cross-process locking and persistence are required before any multi-worker or exchange execution.
- Simulated results are not evidence of profitability or live execution parity.
