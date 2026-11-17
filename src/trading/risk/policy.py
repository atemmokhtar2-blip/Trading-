"""Pure, deterministic pre-trade risk checks.

This module is intentionally independent of exchanges, network services, and AI.
All monetary values use Decimal to avoid binary floating-point surprises.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

ZERO: Final[Decimal] = Decimal("0")
HUNDRED: Final[Decimal] = Decimal("100")


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """Hard limits applied before a proposed trade can be considered."""

    max_risk_per_trade_pct: Decimal = Decimal("0.5")
    max_daily_loss_pct: Decimal = Decimal("1.0")
    max_weekly_loss_pct: Decimal = Decimal("3.0")
    max_monthly_loss_pct: Decimal = Decimal("5.0")
    max_open_positions: int = 1

    def __post_init__(self) -> None:
        percentages = (
            self.max_risk_per_trade_pct,
            self.max_daily_loss_pct,
            self.max_weekly_loss_pct,
            self.max_monthly_loss_pct,
        )
        if any(not value.is_finite() or value <= ZERO for value in percentages):
            raise ValueError("Risk percentages must be finite and greater than zero.")
        if self.max_open_positions < 1:
            raise ValueError("max_open_positions must be at least 1.")


@dataclass(frozen=True, slots=True)
class RiskSnapshot:
    """A point-in-time account snapshot supplied by a trusted account adapter."""

    equity: Decimal
    day_start_equity: Decimal
    week_start_equity: Decimal
    month_start_equity: Decimal
    open_positions: int
    trading_enabled: bool = True


@dataclass(frozen=True, slots=True)
class TradeProposal:
    """The maximum loss in account currency if the proposed stop is reached."""

    risk_amount: Decimal


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """Decision returned by the risk gate; reasons are stable machine-readable codes."""

    allowed: bool
    reason: str
    max_allowed_risk_amount: Decimal = ZERO


def _validate_snapshot(snapshot: RiskSnapshot) -> bool:
    equity_values = (
        snapshot.equity,
        snapshot.day_start_equity,
        snapshot.week_start_equity,
        snapshot.month_start_equity,
    )
    return (
        all(value.is_finite() and value > ZERO for value in equity_values)
        and snapshot.open_positions >= 0
    )


def _drawdown_pct(start_equity: Decimal, current_equity: Decimal) -> Decimal:
    """Return percentage drawdown from a period's starting equity, floored at zero."""

    loss = max(ZERO, start_equity - current_equity)
    return (loss / start_equity) * HUNDRED


def evaluate_trade(
    proposal: TradeProposal,
    snapshot: RiskSnapshot,
    limits: RiskLimits = RiskLimits(),
) -> RiskDecision:
    """Approve or reject a proposal using deterministic hard limits.

    This is a pre-trade gate, not a complete account-level risk system. A production
    integration must refresh the account snapshot immediately before order submission,
    serialize concurrent decisions, and reconcile uncertain order outcomes.
    """

    if not snapshot.trading_enabled:
        return RiskDecision(False, "TRADING_DISABLED")

    if not _validate_snapshot(snapshot):
        return RiskDecision(False, "INVALID_ACCOUNT_SNAPSHOT")

    if not proposal.risk_amount.is_finite() or proposal.risk_amount <= ZERO:
        return RiskDecision(False, "INVALID_PROPOSED_RISK")

    if snapshot.open_positions >= limits.max_open_positions:
        return RiskDecision(False, "MAX_OPEN_POSITIONS_REACHED")

    if _drawdown_pct(snapshot.day_start_equity, snapshot.equity) >= limits.max_daily_loss_pct:
        return RiskDecision(False, "DAILY_LOSS_LIMIT_REACHED")

    if _drawdown_pct(snapshot.week_start_equity, snapshot.equity) >= limits.max_weekly_loss_pct:
        return RiskDecision(False, "WEEKLY_LOSS_LIMIT_REACHED")

    if _drawdown_pct(snapshot.month_start_equity, snapshot.equity) >= limits.max_monthly_loss_pct:
        return RiskDecision(False, "MONTHLY_LOSS_LIMIT_REACHED")

    max_risk_amount = snapshot.equity * limits.max_risk_per_trade_pct / HUNDRED
    if proposal.risk_amount > max_risk_amount:
        return RiskDecision(False, "TRADE_RISK_LIMIT_EXCEEDED", max_risk_amount)

    return RiskDecision(True, "APPROVED", max_risk_amount)
