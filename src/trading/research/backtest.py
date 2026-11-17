"""Deterministic EMA-crossover research backtest with conservative costs.

Signals use completed bars and fill at the following bar open. This is a research
evaluator, not an optimizer or a live trading engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from trading.execution.paper import MarketBar

ZERO = Decimal("0")
TEN_THOUSAND = Decimal("10000")


@dataclass(frozen=True, slots=True)
class CostAssumptions:
    spread_bps: Decimal = Decimal("5")
    slippage_bps: Decimal = Decimal("5")
    commission_bps: Decimal = Decimal("10")

    def __post_init__(self) -> None:
        values = (self.spread_bps, self.slippage_bps, self.commission_bps)
        if any(not value.is_finite() or value < ZERO for value in values):
            raise ValueError("cost assumptions must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class StrategySpec:
    name: str
    fast_period: int
    slow_period: int

    def __post_init__(self) -> None:
        if not self.name.strip() or self.fast_period < 2 or self.slow_period <= self.fast_period:
            raise ValueError("strategy requires 2 <= fast_period < slow_period")


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    entry_time: str
    exit_time: str
    quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal
    net_pnl: Decimal


@dataclass(frozen=True, slots=True)
class BacktestReport:
    strategy: str
    bars_tested: int
    trades: int
    wins: int
    win_rate_pct: Decimal
    initial_cash: Decimal
    ending_equity: Decimal
    net_return_pct: Decimal
    max_drawdown_pct: Decimal
    total_fees: Decimal
    profit_factor: Decimal | None
    trades_detail: tuple[BacktestTrade, ...]


def _ema(values: Sequence[Decimal], period: int) -> list[Decimal]:
    if period < 2:
        raise ValueError("EMA period must be at least 2")
    if len(values) < period:
        return []
    multiplier = Decimal("2") / Decimal(period + 1)
    current = sum(values[:period], ZERO) / Decimal(period)
    result = [current]
    for value in values[period:]:
        current = (value - current) * multiplier + current
        result.append(current)
    return result


def run_ema_backtest(
    bars: Sequence[MarketBar],
    initial_cash: Decimal,
    spec: StrategySpec,
    costs: CostAssumptions = CostAssumptions(),
    *,
    start_index: int = 0,
) -> BacktestReport:
    """Run a one-symbol, long-only all-cash simulation with next-open execution.

    For a chronological holdout, start_index skips trading until the holdout while
    indicator values continue to use only earlier bars. The holdout starts flat.
    """
    if not isinstance(initial_cash, Decimal) or not initial_cash.is_finite() or initial_cash <= ZERO:
        raise ValueError("initial_cash must be a finite positive Decimal")
    if len(bars) < spec.slow_period + 2:
        raise ValueError("not enough bars for strategy warm-up and execution")
    if not 0 <= start_index < len(bars) - 1:
        raise ValueError("start_index must leave at least one execution bar")
    instrument, timeframe = bars[0].instrument, bars[0].timeframe
    if any(bar.instrument != instrument or bar.timeframe != timeframe for bar in bars):
        raise ValueError("backtest input must contain one instrument and timeframe")
    if any(bars[i].timestamp >= bars[i + 1].timestamp for i in range(len(bars) - 1)):
        raise ValueError("bars must be strictly chronological")

    closes = [bar.close for bar in bars]
    fast = _ema(closes, spec.fast_period)
    slow = _ema(closes, spec.slow_period)
    fast_offset, slow_offset = spec.fast_period - 1, spec.slow_period - 1

    cash, quantity, entry_cost, entry_price = initial_cash, ZERO, ZERO, ZERO
    entry_time = ""
    total_fees = ZERO
    completed: list[BacktestTrade] = []
    equity_peak, max_drawdown = initial_cash, ZERO
    first_signal_index = max(spec.slow_period, start_index)

    adverse_rate = (
        costs.spread_bps / Decimal("2") + costs.slippage_bps
    ) / TEN_THOUSAND
    buy_multiplier = Decimal("1") + adverse_rate
    sell_multiplier = Decimal("1") - adverse_rate
    if sell_multiplier <= ZERO:
        raise ValueError("cost assumptions imply a non-positive sell price")
    commission_rate = costs.commission_bps / TEN_THOUSAND

    for signal_index in range(first_signal_index, len(bars) - 1):
        fast_now = fast[signal_index - fast_offset]
        slow_now = slow[signal_index - slow_offset]
        fast_prev = fast[signal_index - 1 - fast_offset]
        slow_prev = slow[signal_index - 1 - slow_offset]
        next_bar = bars[signal_index + 1]
        cross_up = fast_prev <= slow_prev and fast_now > slow_now
        cross_down = fast_prev >= slow_prev and fast_now < slow_now

        if quantity == ZERO and cross_up:
            fill_price = next_bar.open * buy_multiplier
            unit_cost = fill_price * (Decimal("1") + commission_rate)
            quantity = cash / unit_cost
            total_fees += quantity * fill_price * commission_rate
            entry_cost, entry_price = cash, fill_price
            entry_time = next_bar.timestamp.isoformat()
            cash = ZERO
        elif quantity > ZERO and cross_down:
            fill_price = next_bar.open * sell_multiplier
            proceeds = quantity * fill_price * (Decimal("1") - commission_rate)
            total_fees += quantity * fill_price * commission_rate
            completed.append(
                BacktestTrade(
                    entry_time, next_bar.timestamp.isoformat(), quantity,
                    entry_price, fill_price, proceeds - entry_cost,
                )
            )
            cash, quantity, entry_cost = proceeds, ZERO, ZERO

        mark = cash
        if quantity > ZERO:
            mark = quantity * next_bar.close * sell_multiplier * (Decimal("1") - commission_rate)
        equity_peak = max(equity_peak, mark)
        if equity_peak > ZERO:
            max_drawdown = max(
                max_drawdown, (equity_peak - mark) / equity_peak * Decimal("100")
            )

    if quantity > ZERO:
        final_bar = bars[-1]
        fill_price = final_bar.close * sell_multiplier
        proceeds = quantity * fill_price * (Decimal("1") - commission_rate)
        total_fees += quantity * fill_price * commission_rate
        completed.append(
            BacktestTrade(
                entry_time, final_bar.timestamp.isoformat(), quantity,
                entry_price, fill_price, proceeds - entry_cost,
            )
        )
        cash = proceeds

    wins = sum(1 for trade in completed if trade.net_pnl > ZERO)
    gross_profit = sum((t.net_pnl for t in completed if t.net_pnl > ZERO), ZERO)
    gross_loss = -sum((t.net_pnl for t in completed if t.net_pnl < ZERO), ZERO)
    profit_factor = (
        gross_profit / gross_loss if gross_loss > ZERO
        else (None if gross_profit == ZERO else Decimal("Infinity"))
    )
    return_pct = (cash - initial_cash) / initial_cash * Decimal("100")
    win_rate = Decimal(wins) / Decimal(len(completed)) * Decimal("100") if completed else ZERO
    return BacktestReport(
        strategy=spec.name,
        bars_tested=len(bars) - start_index,
        trades=len(completed),
        wins=wins,
        win_rate_pct=win_rate,
        initial_cash=initial_cash,
        ending_equity=cash,
        net_return_pct=return_pct,
        max_drawdown_pct=max_drawdown,
        total_fees=total_fees,
        profit_factor=profit_factor,
        trades_detail=tuple(completed),
    )


def chronological_split(total_bars: int, train_fraction: Decimal = Decimal("0.7")) -> int:
    """Return the first holdout index without shuffling time-series observations."""
    if total_bars < 100:
        raise ValueError("at least 100 bars are required for a meaningful split")
    if not train_fraction.is_finite() or not Decimal("0.5") <= train_fraction <= Decimal("0.9"):
        raise ValueError("train_fraction must be between 0.5 and 0.9")
    split = int(Decimal(total_bars) * train_fraction)
    if split < 1 or split >= total_bars - 1:
        raise ValueError("invalid chronological split")
    return split
