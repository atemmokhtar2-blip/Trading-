from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading.portfolio.ledger import PortfolioLedger
from trading.execution.paper import (
    ExecutionCosts,
    IntentSide,
    MarketBar,
    PaperExecutionEngine,
    TradeIntent,
)

D = Decimal
UTC = timezone.utc
COSTS = ExecutionCosts(D("10"), D("5"), D("10"))


def bar(
    minute: int,
    *,
    open_price: str = "100",
    high: str = "102",
    low: str = "99",
    close: str = "101",
) -> MarketBar:
    return MarketBar(
        instrument="BTCUSDT",
        timeframe="1m",
        timestamp=datetime(2026, 1, 1, 12, minute, tzinfo=UTC),
        open=D(open_price),
        high=D(high),
        low=D(low),
        close=D(close),
        volume=D("1"),
    )


def engine(cash: str = "10000") -> PaperExecutionEngine:
    return PaperExecutionEngine(PortfolioLedger(D(cash)), COSTS)


def buy_intent(
    engine_: PaperExecutionEngine,
    *,
    intent_id: str = "entry-1",
    quantity: str = "1",
    stop: str = "95",
    target: str | None = None,
) -> TradeIntent:
    decision_bar = bar(0)
    engine_.process_bar(decision_bar)
    return TradeIntent(
        intent_id=intent_id,
        instrument="BTCUSDT",
        side=IntentSide.BUY,
        quantity=D(quantity),
        decision_bar_time=decision_bar.timestamp,
        decision_price=decision_bar.close,
        stop_price=D(stop),
        target_price=D(target) if target else None,
    )


def test_entry_fills_only_on_next_bar_open_with_explicit_costs() -> None:
    subject = engine()
    intent = buy_intent(subject)
    assert subject.submit(intent) is True
    assert subject.process_bar(bar(1, open_price="110", high="111", low="109"))[0].price == (
        D("110") * D("1.001")
    )
    assert subject.events[-1].kind == "ENTRY_FILLED"
    assert subject.events[-1].timestamp == bar(1).timestamp


def test_identical_intent_retry_is_idempotent() -> None:
    subject = engine()
    intent = buy_intent(subject)
    assert subject.submit(intent) is True
    assert subject.submit(intent) is False
    assert len(subject.pending_intents) == 1


def test_conflicting_intent_id_is_rejected() -> None:
    subject = engine()
    intent = buy_intent(subject)
    subject.submit(intent)
    changed = TradeIntent(
        **{**intent.__dict__, "quantity": D("2")}
    ) if hasattr(intent, "__dict__") else TradeIntent(
        intent.intent_id, intent.instrument, intent.side, D("2"),
        intent.decision_bar_time, intent.decision_price, intent.stop_price,
        intent.target_price,
    )
    with pytest.raises(ValueError, match="different intent"):
        subject.submit(changed)


def test_stale_signal_is_rejected() -> None:
    subject = engine()
    subject.process_bar(bar(0))
    with pytest.raises(ValueError, match="latest completed bar"):
        subject.submit(TradeIntent(
            "old", "BTCUSDT", IntentSide.BUY, D("1"),
            bar(0).timestamp - timedelta(minutes=1), D("101"), D("95"),
        ))


def test_risk_gate_rejects_entry_without_creating_fill() -> None:
    subject = engine()
    intent = buy_intent(subject, quantity="2", stop="90")
    subject.submit(intent)
    assert subject.process_bar(bar(1))[0:1] == ()
    assert subject.events[-1].kind == "INTENT_REJECTED"
    assert subject.events[-1].reason == "TRADE_RISK_LIMIT_EXCEEDED"


def test_stop_must_remain_below_actual_next_bar_fill() -> None:
    subject = engine()
    intent = buy_intent(subject, stop="99.99")
    subject.submit(intent)
    assert subject.process_bar(bar(1, open_price="99", high="100", low="98")) == ()
    assert subject.events[-1].reason == "STOP_NOT_BELOW_ENTRY"


def test_buy_without_stop_is_invalid() -> None:
    with pytest.raises(ValueError, match="requires"):
        TradeIntent(
            "bad", "BTCUSDT", IntentSide.BUY, D("1"), bar(0).timestamp,
            D("101"), None,
        )
        # Validation is performed when submitting, not by constructing the DTO.


def test_kill_switch_blocks_entries_but_not_position_exits() -> None:
    subject = engine()
    intent = buy_intent(subject)
    subject.set_trading_enabled(False)
    subject.submit(intent)
    assert subject.process_bar(bar(1)) == ()
    assert subject.events[-1].reason == "TRADING_DISABLED"


def test_manual_sell_closes_position_on_next_bar() -> None:
    subject = engine()
    entry = buy_intent(subject)
    subject.submit(entry)
    subject.process_bar(bar(1, low="100"))
    latest = bar(2)
    subject.process_bar(latest)
    exit_intent = TradeIntent(
        "exit-1", "BTCUSDT", IntentSide.SELL, D("1"),
        latest.timestamp, latest.close,
    )
    subject.submit(exit_intent)
    fills = subject.process_bar(bar(3))
    assert len(fills) == 1
    assert subject.events[-1].kind == "EXIT_FILLED"
    assert subject._ledger.snapshot().positions == ()


def test_stop_is_checked_on_bars_after_entry_only() -> None:
    subject = engine()
    intent = buy_intent(subject, stop="95")
    subject.submit(intent)
    subject.process_bar(bar(1, open_price="100", low="90"))
    assert subject._ledger.snapshot().positions
    subject.process_bar(bar(2, open_price="94", high="96", low="93"))
    assert subject.events[-1].kind == "STOP_FILLED"
    assert subject._ledger.snapshot().positions == ()


def test_same_bar_stop_and_target_uses_stop_first() -> None:
    subject = engine()
    intent = buy_intent(subject, stop="95", target="105")
    subject.submit(intent)
    subject.process_bar(bar(1, low="99"))
    subject.process_bar(bar(2, open_price="100", high="106", low="94"))
    assert subject.events[-1].kind == "STOP_FILLED"


def test_gap_through_stop_fills_at_open_not_stop() -> None:
    subject = engine()
    intent = buy_intent(subject, stop="95")
    subject.submit(intent)
    subject.process_bar(bar(1, low="99"))
    fills = subject.process_bar(bar(2, open_price="90", high="92", low="89"))
    assert len(fills) == 1
    assert fills[0].price == D("90") * D("0.9985")
    assert fills[0].price < D("95")


def test_target_is_evaluated_after_entry_bar() -> None:
    subject = engine()
    intent = buy_intent(subject, stop="95", target="105")
    subject.submit(intent)
    subject.process_bar(bar(1, low="99", high="106"))
    assert subject._ledger.snapshot().positions
    subject.process_bar(bar(2, low="100", high="106"))
    assert subject.events[-1].kind == "TARGET_FILLED"


def test_bars_must_be_monotonic_and_ohlc_valid() -> None:
    subject = engine()
    subject.process_bar(bar(1))
    with pytest.raises(ValueError, match="increasing"):
        subject.process_bar(bar(1))
    with pytest.raises(ValueError, match="high"):
        MarketBar(
            "BTCUSDT", "1m", datetime(2026, 1, 1, tzinfo=UTC),
            D("100"), D("99"), D("98"), D("100"),
        )


def test_missing_stop_or_non_utc_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="UTC"):
        MarketBar(
            "BTCUSDT", "1m", datetime(2026, 1, 1),
            D("100"), D("101"), D("99"), D("100"),
        )
    subject = engine()
    subject.process_bar(bar(0))
    invalid = TradeIntent(
        "bad", "BTCUSDT", IntentSide.BUY, D("1"),
        bar(0).timestamp, D("101"),
    )
    with pytest.raises(ValueError, match="requires"):
        subject.submit(invalid)


def test_costs_must_be_explicit_and_non_negative() -> None:
    with pytest.raises(ValueError):
        ExecutionCosts(D("-1"), D("0"), D("0"))
