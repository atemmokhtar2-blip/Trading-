"""Historical strategy evaluation across the current top-ten USDT Spot universe."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, Sequence

from trading.execution.paper import MarketBar
from trading.research.backtest import (
    BacktestReport,
    CostAssumptions,
    StrategySpec,
    chronological_split,
    run_ema_backtest,
)

DEFAULT_STRATEGIES = (
    StrategySpec("EMA 8/21", 8, 21),
    StrategySpec("EMA 12/26", 12, 26),
    StrategySpec("EMA 20/50", 20, 50),
)


class PublicMarketData(Protocol):
    def top_usdt_symbols(self, limit: int = 10) -> list[str]: ...
    def closed_klines(
        self, symbol: str, interval: str = "1h", limit: int = 1000
    ) -> list[MarketBar]: ...


@dataclass(frozen=True, slots=True)
class StrategyEvaluation:
    symbol: str
    strategy: str
    allocated_capital: Decimal
    train: BacktestReport
    holdout: BacktestReport


@dataclass(frozen=True, slots=True)
class ResearchRun:
    symbols: tuple[str, ...]
    interval: str
    candle_count: int
    initial_capital: Decimal
    per_symbol_capital: Decimal
    evaluations: tuple[StrategyEvaluation, ...]


def evaluate_symbol(
    symbol: str,
    bars: Sequence[MarketBar],
    allocated_capital: Decimal,
    strategies: Sequence[StrategySpec] = DEFAULT_STRATEGIES,
    costs: CostAssumptions = CostAssumptions(),
) -> tuple[StrategyEvaluation, ...]:
    """Evaluate candidates on chronological train and unseen holdout periods."""
    split = chronological_split(len(bars))
    train_bars = bars[: split + 1]
    results = []
    for spec in strategies:
        train = run_ema_backtest(train_bars, allocated_capital, spec, costs)
        holdout = run_ema_backtest(
            bars, allocated_capital, spec, costs, start_index=split
        )
        results.append(
            StrategyEvaluation(
                symbol=symbol,
                strategy=spec.name,
                allocated_capital=allocated_capital,
                train=train,
                holdout=holdout,
            )
        )
    return tuple(results)


def evaluate_top_universe(
    client: PublicMarketData,
    initial_capital: Decimal = Decimal("100"),
    *,
    symbol_count: int = 10,
    interval: str = "1h",
    candle_limit: int = 1000,
    strategies: Sequence[StrategySpec] = DEFAULT_STRATEGIES,
    costs: CostAssumptions = CostAssumptions(),
) -> ResearchRun:
    """Fetch and evaluate top pairs sequentially to respect public API rate limits.

    Per-symbol runs are isolated research comparisons, not one shared-cash portfolio.
    """
    if not initial_capital.is_finite() or initial_capital <= 0:
        raise ValueError("initial_capital must be finite and positive")
    symbols = client.top_usdt_symbols(symbol_count)
    if len(symbols) != symbol_count or len(set(symbols)) != symbol_count:
        raise ValueError("market-data adapter returned an invalid symbol universe")
    per_symbol = initial_capital / Decimal(symbol_count)
    all_results: list[StrategyEvaluation] = []
    minimum_history = max(spec.slow_period for spec in strategies) + 2
    if candle_limit < max(100, minimum_history):
        raise ValueError("candle_limit is too small for selected strategies")
    for symbol in symbols:
        bars = client.closed_klines(symbol, interval=interval, limit=candle_limit)
        if len(bars) < minimum_history:
            raise ValueError(f"insufficient history for {symbol}")
        all_results.extend(
            evaluate_symbol(symbol, bars, per_symbol, strategies, costs)
        )
    return ResearchRun(
        symbols=tuple(symbols),
        interval=interval,
        candle_count=candle_limit,
        initial_capital=initial_capital,
        per_symbol_capital=per_symbol,
        evaluations=tuple(all_results),
    )
