"""Deterministic signal and position sizing for the live paper loop.

Pure functions over completed bars. No network, persistence, or AI access.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from trading.execution.paper import MarketBar
from trading.research.backtest import _ema

ZERO = Decimal("0")
HUNDRED = Decimal("100")


class Signal(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True, slots=True)
class StrategyParams:
    """EMA crossover with a trend filter and ATR-based protective levels."""

    fast_period: int = 12
    slow_period: int = 26
    trend_period: int = 100
    atr_period: int = 14
    stop_atr_multiple: Decimal = Decimal("2")
    target_atr_multiple: Decimal = Decimal("3")
    # Must stay below RiskLimits.max_risk_per_trade_pct; the gap pays for fees/slippage.
    risk_per_trade_pct: Decimal = Decimal("0.4")
    max_cash_fraction: Decimal = Decimal("0.95")

    def __post_init__(self) -> None:
        if not 2 <= self.fast_period < self.slow_period < self.trend_period:
            raise ValueError("require 2 <= fast < slow < trend periods")
        if self.atr_period < 2:
            raise ValueError("atr_period must be at least 2")
        multiples = (self.stop_atr_multiple, self.target_atr_multiple)
        if any(not m.is_finite() or m <= ZERO for m in multiples):
            raise ValueError("ATR multiples must be finite and positive")
        if not self.risk_per_trade_pct.is_finite() or self.risk_per_trade_pct <= ZERO:
            raise ValueError("risk_per_trade_pct must be finite and positive")
        if not ZERO < self.max_cash_fraction <= Decimal("1"):
            raise ValueError("max_cash_fraction must be in (0, 1]")

    @property
    def min_bars(self) -> int:
        return self.trend_period + 2


def average_true_range(bars: Sequence[MarketBar], period: int) -> Decimal | None:
    """Simple average of the last `period` true ranges, or None without enough bars."""
    if period < 2 or len(bars) < period + 1:
        return None
    total = ZERO
    for index in range(len(bars) - period, len(bars)):
        current, previous_close = bars[index], bars[index - 1].close
        total += max(
            current.high - current.low,
            abs(current.high - previous_close),
            abs(current.low - previous_close),
        )
    return total / Decimal(period)


def latest_signal(
    bars: Sequence[MarketBar], params: StrategyParams, *, in_position: bool
) -> Signal | None:
    """Signal for the most recent completed bar only.

    BUY: fast EMA crosses above slow EMA while price is above the trend EMA, flat.
    SELL: fast EMA crosses below slow EMA while holding.
    """
    if len(bars) < params.min_bars:
        return None
    closes = [bar.close for bar in bars]
    fast = _ema(closes, params.fast_period)
    slow = _ema(closes, params.slow_period)
    trend = _ema(closes, params.trend_period)
    cross_up = fast[-2] <= slow[-2] and fast[-1] > slow[-1]
    cross_down = fast[-2] >= slow[-2] and fast[-1] < slow[-1]
    if not in_position and cross_up and closes[-1] > trend[-1]:
        return Signal.BUY
    if in_position and cross_down:
        return Signal.SELL
    return None


def entry_levels(
    bars: Sequence[MarketBar], params: StrategyParams
) -> tuple[Decimal, Decimal] | None:
    """Return (stop, target) from ATR at the latest close, or None if invalid."""
    atr = average_true_range(bars, params.atr_period)
    if atr is None or atr <= ZERO:
        return None
    price = bars[-1].close
    stop = price - atr * params.stop_atr_multiple
    if stop <= ZERO:
        return None
    return stop, price + atr * params.target_atr_multiple


def position_quantity(
    equity: Decimal,
    cash: Decimal,
    price: Decimal,
    stop: Decimal,
    params: StrategyParams,
) -> Decimal:
    """Size so that hitting the stop loses about risk_per_trade_pct of equity.

    Capped by available cash. Returns zero when no valid size exists.
    """
    risk_per_unit = price - stop
    if equity <= ZERO or cash <= ZERO or price <= ZERO or risk_per_unit <= ZERO:
        return ZERO
    by_risk = equity * params.risk_per_trade_pct / HUNDRED / risk_per_unit
    by_cash = cash * params.max_cash_fraction / price
    return min(by_risk, by_cash)
