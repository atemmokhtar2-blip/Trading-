# Paper Trading Foundation — Milestone 1

## Status

Design contract for the first autonomous simulation milestone. This milestone is simulation-only. It must not connect to a broker, request credentials, or submit live orders.

## Goal

Create a deterministic, auditable paper-trading environment in which the system can:
1. Receive validated market bars from a replaceable data source.
2. Ask a strategy for a trade intent.
3. pass every intent through the existing deterministic risk policy.
4. Simulate fills using an explicit execution model.
5. Maintain a virtual cash/equity/position ledger.
6. Record every input, decision, rejection, fill, fee, and state transition.
7. Replay the same inputs and obtain the same results.

The first implementation is deliberately instrument- and broker-independent.

## Non-goals

- No real-money trading or broker connectivity.
- No MetaTrader 5 dependency.
- No AI-generated orders or AI-controlled risk settings.
- No leverage, short selling, derivatives, martingale, grid, or averaging down in the first simulator.
- No claim that simulated results predict live profitability.
- No strategy optimization until the simulator's accounting and execution semantics are tested.

## Domain boundaries

### Market data

A bar is immutable and contains:
- instrument identifier;
- timeframe;
- UTC timestamp for bar open;
- open, high, low, close;
- volume where available;
- source identifier.

Validation must reject non-finite or non-positive OHLC values, impossible OHLC relationships, negative volume, duplicate/out-of-order timestamps, and incomplete bars where the source can identify them. The engine must never silently forward-fill missing market prices.

### Strategy

A strategy receives only the market history available at the decision timestamp and its own explicit state. It returns an intent, not an executable broker order. It cannot access future bars, the account ledger internals, secrets, network services, or risk configuration.

The first strategy should be a transparent baseline used to test plumbing, not advertised as profitable. Strategy versions and parameters must be recorded with every decision.

### Risk gate

The existing risk policy remains deterministic and independent of market data providers, AI, and execution adapters. The simulator must calculate the proposed loss from entry, stop distance, quantity, and instrument contract assumptions before asking the risk gate. An intent without a valid protective stop is rejected.

Risk checks must use current virtual equity and current exposure. Rejections are first-class audit events. Risk defaults remain engineering placeholders until instrument specifications and costs are known.

### Paper execution

The execution model must be explicit and conservative:
- A signal produced after a bar closes cannot fill at that same bar's already-known close.
- Default market-order simulation fills no earlier than the next available bar, using a documented price rule.
- Spread, commission, and slippage are explicit inputs; never silently assumed to be zero in performance reports.
- Stops/targets are evaluated only using prices available after entry. If a bar touches both stop and target and lower-resolution data cannot establish order, use the adverse assumption (stop first).
- Gaps through stops fill at the first realistically available price, not the requested stop price.
- Partial fills and unavailable liquidity are future extensions; the initial model must clearly state its simplified fill assumptions.

### Portfolio ledger

Use decimal arithmetic for money and quantities where practical. Track cash, realized P&L, unrealized P&L, fees, open positions, and equity. Every fill and accounting mutation must be traceable to an event. No direct mutation from strategy code.

The ledger must enforce:
- no negative position quantity in the initial long-only model;
- no sale quantity greater than the open position;
- no double application of the same fill/event identifier;
- fees deducted exactly once;
- equity reconciles to cash plus marked-to-market position value;
- closed-trade P&L reconciles with realized ledger movements.

### Replay and audit

Given the same ordered market data, configuration, strategy version, and simulator version, replay must be deterministic. Persist or export enough metadata to reproduce a run: data-source/version or dataset hash, date range, timeframe, strategy ID/version/parameters, execution-cost assumptions, risk limits, and software version.

## Required test gates

Before this milestone can be called complete:
- unit tests for bar validation and timestamp ordering;
- ledger tests for buys, sells, fees, realized/unrealized P&L, and equity reconciliation;
- duplicate-event/idempotency tests;
- risk rejection and no-fill tests;
- no-lookahead tests;
- next-bar execution tests;
- stop/target same-bar ambiguity tests;
- gap-through-stop tests;
- deterministic replay tests;
- malformed, missing, stale, and out-of-order data tests;
- static checks and full test suite.

A passing unit-test suite proves implementation behavior only. It does not prove that a strategy is profitable or safe for live trading.

## Promotion policy

The system stays in simulation by default. No live adapter may be added until:
1. the simulator and accounting tests pass;
2. historical data quality and costs are independently checked;
3. out-of-sample and walk-forward evaluation are completed;
4. stress and failure tests are documented;
5. demo forward testing is completed;
6. a separate explicit review approves any later broker integration.

Live execution remains disabled by default even after those gates.
