# Safety and validation gates

## Non-negotiable operating policy

- Development starts offline; all authenticated exchange integration starts on Binance Spot Testnet.
- No live order execution is enabled by default, and the initial configuration must reject production trading endpoints/credentials.
- No target return is promised or used as an acceptance criterion.
- Never increase risk to recover losses; no martingale, grid averaging, or loss-chasing.
- Never trade with borrowed money or money needed for living costs.
- Do not leave the day job or rely on trading income based on a short demo or live sample.

## Exchange scope

The initial exchange target is Binance Spot only. Margin, Futures, leverage, and short selling are excluded. Public market data can be consumed without API keys. Testnet credentials are introduced only when the authenticated Testnet adapter is implemented; they must be stored as Railway secrets, have minimum permissions, and never include withdrawal permission. No API key or secret may appear in source control, logs, exception text, or audit payloads.

## Risk policy status

The initial risk module is a pure pre-trade gate. Its default percentages are conservative engineering placeholders, not a recommendation or proof that Binance symbol minimums can satisfy the limits. A trade must be rejected when its minimum permitted quantity risks more than the configured cap.

The current module does not yet implement:
- exchange-side protective-order verification,
- balance and floating P&L reconciliation,
- daily reset/time-zone policy,
- durable risk state across restarts,
- concurrent order locking and worker ownership,
- portfolio/correlation exposure,
- gap/slippage stress limits,
- quote-asset and account-currency conversion,
- Binance symbol filter and precision validation.

Those must be implemented and tested before any authenticated Testnet execution, and independently reviewed before any live use.

## Validation sequence

1. Unit tests for pure domain rules.
2. Static analysis, type checking, and CI.
3. Deterministic backtests with explicit spread, commission, and slippage assumptions.
4. Out-of-sample and walk-forward validation; no tuning on the final holdout.
5. Monte Carlo / parameter sensitivity and regime analysis.
6. Binance Spot Testnet forward test with exchange-specific symbol filters and order-state behavior.
7. Failure tests: stale quote, disconnect, rate limit, timeout, partial fill, duplicate event, worker restart, database outage, and unknown order outcome.
8. Independent review of logs, drawdown, and simulated/Testnet execution parity.
9. Live trading remains disabled unless a separate explicit review approves it after all gates pass.

## Performance reporting

Report net return, max drawdown, profit factor, expectancy, trade count, average win/loss, exposure time, costs, and confidence/uncertainty. A high win rate alone is insufficient. Compare results with a simple baseline and preserve untouched out-of-sample periods.

## Change control

Every meaningful change must include:
- the problem it solves,
- alternatives considered,
- tests added or updated,
- test output,
- rollback path,
- documentation updates when architecture or risk policy changes.
