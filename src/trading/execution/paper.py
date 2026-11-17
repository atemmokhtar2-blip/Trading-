"""Deterministic, long-only paper execution with conservative bar semantics.

This engine is deliberately offline. It consumes normalized bars and emits simulated
fills into the portfolio ledger; it has no exchange, network, persistence, or AI access.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Final

from trading.portfolio.ledger import Fill, FillSide, PortfolioLedger
from trading.risk.policy import (
    RiskLimits,
    RiskSnapshot,
    TradeProposal,
    evaluate_trade,
)

ZERO: Final[Decimal] = Decimal("0")
TEN_THOUSAND: Final[Decimal] = Decimal("10000")


class IntentSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True, slots=True)
class MarketBar:
    """A completed OHLCV bar; timestamp is the UTC bar-open time."""

    instrument: str
    timeframe: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None
    source: str = "test"

    def __post_init__(self) -> None:
        if not self.instrument.strip() or not self.timeframe.strip() or not self.source.strip():
            raise ValueError("instrument, timeframe, and source must be non-empty")
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() != timedelta(0):
            raise ValueError("bar timestamp must be timezone-aware UTC")
        prices = (self.open, self.high, self.low, self.close)
        if any(not isinstance(value, Decimal) or not value.is_finite() or value <= ZERO
               for value in prices):
            raise ValueError("OHLC prices must be finite positive Decimals")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("bar high is inconsistent with OHLC values")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("bar low is inconsistent with OHLC values")
        if self.volume is not None and (
            not isinstance(self.volume, Decimal)
            or not self.volume.is_finite()
            or self.volume < ZERO
        ):
            raise ValueError("volume must be a finite non-negative Decimal")


@dataclass(frozen=True, slots=True)
class TradeIntent:
    """A strategy request, not an exchange order or a fill."""

    intent_id: str
    instrument: str
    side: IntentSide
    quantity: Decimal
    decision_bar_time: datetime
    decision_price: Decimal
    stop_price: Decimal | None = None
    target_price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ExecutionCosts:
    """Explicit costs in basis points; zero is allowed only when explicitly configured."""

    spread_bps: Decimal
    slippage_bps: Decimal
    commission_bps: Decimal

    def __post_init__(self) -> None:
        values = (self.spread_bps, self.slippage_bps, self.commission_bps)
        if any(
            not isinstance(value, Decimal) or not value.is_finite() or value < ZERO
            for value in values
        ):
            raise ValueError("execution costs must be finite non-negative Decimals")


@dataclass(frozen=True, slots=True)
class ExecutionEvent:
    event_id: str
    kind: str
    instrument: str
    timestamp: datetime
    intent_id: str | None = None
    fill_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class _PendingIntent:
    intent: TradeIntent


@dataclass(frozen=True, slots=True)
class _Bracket:
    stop_price: Decimal
    target_price: Decimal | None


class PaperExecutionEngine:
    """Single-process deterministic paper executor for one virtual portfolio.

    Signals are accepted only against the latest completed bar and fill no earlier
    than the next bar's open. Protective exits are evaluated on subsequent bars.
    """

    def __init__(
        self,
        ledger: PortfolioLedger,
        costs: ExecutionCosts,
        risk_limits: RiskLimits | None = None,
        *,
        trading_enabled: bool = True,
    ) -> None:
        if not isinstance(ledger, PortfolioLedger):
            raise TypeError("ledger must be a PortfolioLedger")
        if not isinstance(costs, ExecutionCosts):
            raise TypeError("costs must be explicitly configured")
        self._ledger = ledger
        self._costs = costs
        self._risk_limits = risk_limits if risk_limits is not None else RiskLimits()
        self._trading_enabled = trading_enabled
        self._period_start_equity = ledger.snapshot().equity
        self._latest_bars: dict[str, MarketBar] = {}
        self._pending: dict[str, _PendingIntent] = {}
        self._intents: dict[str, TradeIntent] = {}
        self._brackets: dict[str, _Bracket] = {}
        self._events: list[ExecutionEvent] = []
        self._event_counter = 0
        self._fill_counter = 0

    @property
    def events(self) -> tuple[ExecutionEvent, ...]:
        return tuple(self._events)

    @property
    def pending_intents(self) -> tuple[TradeIntent, ...]:
        return tuple(item.intent for _, item in sorted(self._pending.items()))

    def set_trading_enabled(self, enabled: bool) -> None:
        """Disable new entries without preventing exits or protective stops."""
        self._trading_enabled = enabled

    def submit(self, intent: TradeIntent) -> bool:
        """Queue an intent from the latest completed bar; identical retries are idempotent."""
        self._validate_intent(intent)
        previous = self._intents.get(intent.intent_id)
        if previous is not None:
            if previous == intent:
                return False
            raise ValueError("intent_id already exists with different intent data")

        latest = self._latest_bars.get(intent.instrument)
        if latest is None or latest.timestamp != intent.decision_bar_time:
            raise ValueError("intent must reference the latest completed bar")
        if intent.instrument in self._pending:
            raise ValueError("an intent is already pending for this instrument")

        self._intents[intent.intent_id] = intent
        self._pending[intent.instrument] = _PendingIntent(intent)
        self._record("INTENT_ACCEPTED", intent.instrument, intent.decision_bar_time,
                     intent_id=intent.intent_id)
        return True

    def process_bar(self, bar: MarketBar) -> tuple[Fill, ...]:
        """Process one completed bar and return fills created during this call."""
        if not isinstance(bar, MarketBar):
            raise TypeError("bar must be a MarketBar")
        previous = self._latest_bars.get(bar.instrument)
        if previous is not None:
            if bar.timestamp <= previous.timestamp:
                raise ValueError("bars must be strictly increasing by timestamp")
            if bar.timeframe != previous.timeframe or bar.source != previous.source:
                raise ValueError("timeframe and source must remain consistent per instrument")

        created: list[Fill] = []

        # Stops/targets attached on earlier bars are evaluated before new entries.
        bracket = self._brackets.get(bar.instrument)
        if bracket is not None and bar.instrument in {
            position.instrument for position in self._ledger.snapshot().positions
        }:
            exit_price, exit_reason = self._protective_exit_price(bar, bracket)
            if exit_price is not None:
                fill = self._make_fill(
                    bar.instrument, FillSide.SELL,
                    self._open_quantity(bar.instrument), exit_price,
                )
                self._ledger.apply_fill(fill)
                created.append(fill)
                self._brackets.pop(bar.instrument, None)
                self._record(exit_reason, bar.instrument, bar.timestamp, fill_id=fill.fill_id)

        pending = self._pending.pop(bar.instrument, None)
        if pending is not None:
            intent = pending.intent
            if intent.side is IntentSide.BUY:
                fill_price = self._market_fill_price(bar.open, buy=True)
                reason = self._entry_rejection(intent, fill_price)
                if reason is None:
                    risk_amount = self._risk_amount(intent, fill_price)
                    snapshot = self._ledger.snapshot()
                    decision = evaluate_trade(
                        TradeProposal(risk_amount),
                        RiskSnapshot(
                            equity=snapshot.equity,
                            day_start_equity=self._period_start_equity,
                            week_start_equity=self._period_start_equity,
                            month_start_equity=self._period_start_equity,
                            open_positions=len(snapshot.positions),
                            trading_enabled=self._trading_enabled,
                        ),
                        self._risk_limits,
                    )
                    if not decision.allowed:
                        reason = decision.reason
                if reason is None:
                    fill = self._make_fill(
                        intent.instrument, FillSide.BUY, intent.quantity, fill_price
                    )
                    try:
                        self._ledger.apply_fill(fill)
                    except ValueError as exc:
                        if "insufficient cash" not in str(exc):
                            raise
                        reason = "INSUFFICIENT_CASH"
                    else:
                        self._brackets[intent.instrument] = _Bracket(
                            intent.stop_price or ZERO, intent.target_price
                        )
                        created.append(fill)
                        self._record("ENTRY_FILLED", bar.instrument, bar.timestamp,
                                     intent_id=intent.intent_id, fill_id=fill.fill_id)
                if reason is not None:
                    self._record("INTENT_REJECTED", bar.instrument, bar.timestamp,
                                 intent_id=intent.intent_id, reason=reason)
            else:
                if self._open_quantity(intent.instrument) < intent.quantity:
                    self._record("INTENT_REJECTED", bar.instrument, bar.timestamp,
                                 intent_id=intent.intent_id, reason="INSUFFICIENT_POSITION")
                else:
                    fill_price = self._market_fill_price(bar.open, buy=False)
                    fill = self._make_fill(
                        intent.instrument, FillSide.SELL, intent.quantity, fill_price
                    )
                    self._ledger.apply_fill(fill)
                    created.append(fill)
                    if self._open_quantity(intent.instrument) == ZERO:
                        self._brackets.pop(intent.instrument, None)
                    self._record("EXIT_FILLED", bar.instrument, bar.timestamp,
                                 intent_id=intent.intent_id, fill_id=fill.fill_id)

        self._latest_bars[bar.instrument] = bar
        if self._open_quantity(bar.instrument) > ZERO:
            self._ledger.mark_to_market(bar.instrument, bar.close)
        return tuple(created)

    @staticmethod
    def _validate_intent(intent: TradeIntent) -> None:
        if not isinstance(intent, TradeIntent):
            raise TypeError("intent must be a TradeIntent")
        if not intent.intent_id.strip() or not intent.instrument.strip():
            raise ValueError("intent_id and instrument must be non-empty")
        if not isinstance(intent.side, IntentSide):
            raise ValueError("side must be BUY or SELL")
        if not isinstance(intent.quantity, Decimal) or not intent.quantity.is_finite() \
                or intent.quantity <= ZERO:
            raise ValueError("quantity must be a finite positive Decimal")
        if intent.decision_bar_time.tzinfo is None or (
            intent.decision_bar_time.utcoffset() != timedelta(0)
        ):
            raise ValueError("decision_bar_time must be timezone-aware UTC")
        if not isinstance(intent.decision_price, Decimal) or (
            not intent.decision_price.is_finite() or intent.decision_price <= ZERO
        ):
            raise ValueError("decision_price must be a finite positive Decimal")
        if intent.side is IntentSide.BUY:
            if not isinstance(intent.stop_price, Decimal) or not intent.stop_price.is_finite() \
                    or intent.stop_price <= ZERO:
                raise ValueError("BUY intent requires a finite positive protective stop")
            if intent.stop_price >= intent.decision_price:
                raise ValueError("BUY stop must be below decision price")
            if intent.target_price is not None and (
                not isinstance(intent.target_price, Decimal)
                or not intent.target_price.is_finite()
                or intent.target_price <= intent.decision_price
            ):
                raise ValueError("BUY target must be above decision price")
        elif intent.stop_price is not None or intent.target_price is not None:
            raise ValueError("SELL intent cannot define entry stop or target")

    def _market_fill_price(self, raw_price: Decimal, *, buy: bool) -> Decimal:
        half_spread = self._costs.spread_bps / Decimal("2")
        adverse_bps = half_spread + self._costs.slippage_bps
        multiplier = (
            Decimal("1") + adverse_bps / TEN_THOUSAND
            if buy else Decimal("1") - adverse_bps / TEN_THOUSAND
        )
        if multiplier <= ZERO:
            raise ValueError("execution costs imply a non-positive fill price")
        return raw_price * multiplier

    def _commission(self, quantity: Decimal, price: Decimal) -> Decimal:
        return quantity * price * self._costs.commission_bps / TEN_THOUSAND

    def _make_fill(
        self, instrument: str, side: FillSide, quantity: Decimal, price: Decimal
    ) -> Fill:
        self._fill_counter += 1
        return Fill(
            fill_id=f"paper-{self._fill_counter:012d}",
            instrument=instrument,
            side=side,
            quantity=quantity,
            price=price,
            fee=self._commission(quantity, price),
        )

    def _risk_amount(self, intent: TradeIntent, entry_price: Decimal) -> Decimal:
        assert intent.stop_price is not None
        stop_fill = self._market_fill_price(intent.stop_price, buy=False)
        entry_fee = self._commission(intent.quantity, entry_price)
        exit_fee = self._commission(intent.quantity, stop_fill)
        return max(ZERO, (entry_price - stop_fill) * intent.quantity) + entry_fee + exit_fee

    def _entry_rejection(self, intent: TradeIntent, fill_price: Decimal) -> str | None:
        if intent.stop_price is None or intent.stop_price >= fill_price:
            return "STOP_NOT_BELOW_ENTRY"
        if intent.target_price is not None and intent.target_price <= fill_price:
            return "TARGET_NOT_ABOVE_ENTRY"
        return None

    def _protective_exit_price(
        self, bar: MarketBar, bracket: _Bracket
    ) -> tuple[Decimal | None, str]:
        stop_hit = bar.low <= bracket.stop_price
        target_hit = bracket.target_price is not None and bar.high >= bracket.target_price
        if stop_hit:
            # A gap below the stop exits at the open, never at the better stop price.
            raw = min(bar.open, bracket.stop_price)
            return self._market_fill_price(raw, buy=False), "STOP_FILLED"
        if target_hit:
            # Conservative limit assumption: do not grant favorable gap improvement.
            assert bracket.target_price is not None
            return self._market_fill_price(bracket.target_price, buy=False), "TARGET_FILLED"
        return None, ""

    def _open_quantity(self, instrument: str) -> Decimal:
        for position in self._ledger.snapshot().positions:
            if position.instrument == instrument:
                return position.quantity
        return ZERO

    def _record(
        self,
        kind: str,
        instrument: str,
        timestamp: datetime,
        *,
        intent_id: str | None = None,
        fill_id: str | None = None,
        reason: str | None = None,
    ) -> None:
        self._event_counter += 1
        self._events.append(
            ExecutionEvent(
                event_id=f"execution-{self._event_counter:012d}",
                kind=kind,
                instrument=instrument,
                timestamp=timestamp,
                intent_id=intent_id,
                fill_id=fill_id,
                reason=reason,
            )
        )
