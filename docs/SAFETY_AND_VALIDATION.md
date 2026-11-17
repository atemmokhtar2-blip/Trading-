# Safety and validation gates

## Non-negotiable operating policy

- Development starts offline; all broker integration starts on a demo account.
- No live order execution is enabled by default.
- No target return is promised or used as an acceptance criterion.
- Never increase risk to recover losses; no martingale, grid averaging, or loss-chasing.
- Never trade with borrowed money or money needed for living costs.
- Do not leave the day job or rely on trading income based on a short demo or live sample.

## Risk policy status

The initial risk module is a pure pre-trade gate. Its default percentages are conservative engineering placeholders, not a recommendation or proof that a given broker's minimum volume can satisfy the limits. A trade must be rejected when its minimum executable size risks more than the configured cap.

The current module does not yet implement:
- broker-side stop verification,
- floating P&L reconciliation,
- daily reset/time-zone policy,
- persistence across restarts,
- concurrent order locking,
- portfolio/correlation exposure,
- gap/slippage stress limits,
- account-currency conversion.

Those must be implemented and tested before any live use.

## Validation sequence

1. Unit tests for pure domain rules.
2. Static analysis, type checking, and CI.
3. Deterministic backtests with spread, commission, swaps, and realistic fills.
4. Out-of-sample and walk-forward validation; no tuning on the final holdout.
5. Monte Carlo / parameter sensitivity and regime analysis.
6. Demo forward test with broker-specific symbol specifications.
7. Failure tests: stale quote, disconnect, timeout, partial fill, duplicate event, restart, and unknown order outcome.
8. Independent review of logs, drawdown, and execution parity.
9. Live trading remains a separate, explicit decision after all gates pass.

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
