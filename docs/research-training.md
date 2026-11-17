# Binance market-data research and paper training

## Approved operating mode

- Spot public market data only. The collector uses public REST endpoints and requires no Binance API key or secret.
- No account endpoints, API-key authentication, order endpoints, withdrawals, transfers, Futures, Margin, or leverage.
- All executions in this milestone are offline simulations. Nothing can place a live order.
- Requested initial paper capital for the next portfolio integration: **100 USDT**.

## Market universe

The public collector selects the ten highest 24-hour quote-volume eligible Binance Spot pairs quoted in USDT. It excludes stablecoin base assets and leveraged-token suffixes, and checks that the symbol is trading and Spot trading is allowed. The ranking is dynamic and may change between runs.

## Historical research

The collector requests up to 1,000 candles per symbol and removes the currently open candle using Binance server time. The research backtester includes:
- EMA crossover candidates (fast/slow periods are explicit and versioned by the caller).
- Signals only from completed candles.
- Simulated fills at the following candle open, never the signal candle close.
- Explicit non-zero default costs: 5 bps spread, 5 bps slippage, and 10 bps commission per side. These are conservative placeholders, not a claim about the user's actual Binance fee tier or actual spread.
- A chronological train/holdout split; no random shuffling.
- Long-only, Spot-style accounting. No shorting or leverage.

Each symbol's backtest is an isolated research run. Do not add ten per-symbol results together as if they were a single 100 USDT portfolio. A shared-cash multi-symbol portfolio simulator and persistent run/fill records must be implemented and tested before aggregate portfolio performance is reported.

## Live-data phase

This milestone supplies a read-only public REST adapter and historical backtest core. It does **not yet** run a continuous live-data polling loop or connect these research results to Telegram controls. Those are separate integration steps. The existing Railway process still runs Telegram polling and a heartbeat only.

## Interpretation

This is deterministic strategy evaluation, not machine-learning training. A high historical win rate alone is not evidence of profitability. Reports must include net return after costs, drawdown, trade count, win rate, and profit factor, and must be checked on unseen periods before any further paper-forward testing.
