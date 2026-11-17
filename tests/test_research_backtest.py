from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading.execution.paper import MarketBar
from trading.research.backtest import (
    CostAssumptions,
    StrategySpec,
    chronological_split,
    run_ema_backtest,
)


def make_bars(closes: list[str]) -> list[MarketBar]:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    bars = []
    previous = Decimal(closes[0])
    for index, raw in enumerate(closes):
        close = Decimal(raw)
        open_price = previous
        bars.append(
            MarketBar(
                instrument="BTCUSDT",
                timeframe="1h",
                timestamp=start + timedelta(hours=index),
                open=open_price,
                high=max(open_price, close) * Decimal("1.001"),
                low=min(open_price, close) * Decimal("0.999"),
                close=close,
                volume=Decimal("10"),
                source="test",
            )
        )
        previous = close
    return bars


def test_backtest_uses_completed_bars_and_charges_costs() -> None:
    prices = [
        str(200 - i) if i < 40
        else str(160 + (i - 39) * 2) if i < 80
        else str(240 - (i - 79) * 2)
        for i in range(120)
    ]
    report = run_ema_backtest(
        make_bars(prices),
        Decimal("100"),
        StrategySpec("fast-slow", 5, 12),
        CostAssumptions(Decimal("5"), Decimal("5"), Decimal("10")),
    )
    assert report.bars_tested == 120
    assert report.total_fees > 0
    assert report.ending_equity.is_finite()
    assert report.max_drawdown_pct >= 0


def test_backtest_rejects_insufficient_history() -> None:
    with pytest.raises(ValueError):
        run_ema_backtest(
            make_bars(["100"] * 20), Decimal("100"), StrategySpec("x", 5, 20)
        )


def test_chronological_split_is_not_randomized() -> None:
    assert chronological_split(1000) == 700
    with pytest.raises(ValueError):
        chronological_split(50)


def test_strategy_periods_must_be_ordered() -> None:
    with pytest.raises(ValueError):
        StrategySpec("bad", 20, 10)


def test_symbol_evaluation_uses_chronological_train_and_holdout() -> None:
    from trading.research.trainer import evaluate_symbol

    prices = [
        str(200 - i) if i < 40
        else str(160 + (i - 39) * 2) if i < 80
        else str(240 - (i - 79) * 2)
        for i in range(120)
    ]
    results = evaluate_symbol(
        "BTCUSDT",
        make_bars(prices),
        Decimal("10"),
        strategies=(StrategySpec("fast-slow", 5, 12),),
    )
    assert len(results) == 1
    assert results[0].allocated_capital == Decimal("10")
    assert results[0].train.bars_tested == 85
    assert results[0].holdout.bars_tested == 36
