from decimal import Decimal

import pytest

from trading.risk.policy import (
    RiskLimits,
    RiskSnapshot,
    TradeProposal,
    evaluate_trade,
)


def snapshot(**overrides: object) -> RiskSnapshot:
    values: dict[str, object] = {
        "equity": Decimal("2000"),
        "day_start_equity": Decimal("2000"),
        "week_start_equity": Decimal("2000"),
        "month_start_equity": Decimal("2000"),
        "open_positions": 0,
        "trading_enabled": True,
    }
    values.update(overrides)
    return RiskSnapshot(**values)  # type: ignore[arg-type]


def test_approves_trade_within_all_limits() -> None:
    decision = evaluate_trade(TradeProposal(Decimal("10")), snapshot())

    assert decision.allowed is True
    assert decision.reason == "APPROVED"
    assert decision.max_allowed_risk_amount == Decimal("10.000")


def test_rejects_trade_above_per_trade_risk_limit() -> None:
    decision = evaluate_trade(TradeProposal(Decimal("10.01")), snapshot())

    assert decision.allowed is False
    assert decision.reason == "TRADE_RISK_LIMIT_EXCEEDED"


def test_rejects_when_daily_loss_limit_is_reached() -> None:
    account = snapshot(equity=Decimal("1980"))

    decision = evaluate_trade(TradeProposal(Decimal("1")), account)

    assert decision.reason == "DAILY_LOSS_LIMIT_REACHED"


def test_rejects_when_weekly_loss_limit_is_reached() -> None:
    account = snapshot(
        equity=Decimal("1940"),
        day_start_equity=Decimal("2000"),
        week_start_equity=Decimal("2000"),
    )

    decision = evaluate_trade(TradeProposal(Decimal("1")), account)

    assert decision.reason == "WEEKLY_LOSS_LIMIT_REACHED"


def test_rejects_when_monthly_loss_limit_is_reached() -> None:
    account = snapshot(
        equity=Decimal("1900"),
        day_start_equity=Decimal("2000"),
        week_start_equity=Decimal("2000"),
        month_start_equity=Decimal("2000"),
    )

    decision = evaluate_trade(TradeProposal(Decimal("1")), account)

    assert decision.reason == "MONTHLY_LOSS_LIMIT_REACHED"


def test_rejects_when_position_limit_is_reached() -> None:
    account = snapshot(open_positions=1)

    decision = evaluate_trade(TradeProposal(Decimal("1")), account)

    assert decision.reason == "MAX_OPEN_POSITIONS_REACHED"


def test_rejects_when_trading_is_disabled() -> None:
    account = snapshot(trading_enabled=False)

    decision = evaluate_trade(TradeProposal(Decimal("1")), account)

    assert decision.reason == "TRADING_DISABLED"


@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-1"), Decimal("NaN")])
def test_rejects_invalid_proposed_risk(amount: Decimal) -> None:
    decision = evaluate_trade(TradeProposal(amount), snapshot())

    assert decision.reason == "INVALID_PROPOSED_RISK"


def test_rejects_invalid_account_equity() -> None:
    account = snapshot(equity=Decimal("0"))

    decision = evaluate_trade(TradeProposal(Decimal("1")), account)

    assert decision.reason == "INVALID_ACCOUNT_SNAPSHOT"


def test_limits_reject_non_positive_percentages() -> None:
    with pytest.raises(ValueError):
        RiskLimits(max_daily_loss_pct=Decimal("0"))
