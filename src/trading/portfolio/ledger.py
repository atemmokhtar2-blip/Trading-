"""Deterministic long-only paper portfolio ledger.

This module has no broker, network, persistence, or AI dependencies. All monetary
and quantity values are Decimal. It models fills supplied by a paper execution
engine; it does not create orders or claim realistic market execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final

ZERO: Final[Decimal] = Decimal("0")


class FillSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True, slots=True)
class Fill:
    """A simulated execution event. Prices and fees use account currency units."""

    fill_id: str
    instrument: str
    side: FillSide
    quantity: Decimal
    price: Decimal
    fee: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class Position:
    instrument: str
    quantity: Decimal
    average_entry_price: Decimal
    remaining_entry_fees: Decimal


@dataclass(frozen=True, slots=True)
class LedgerSnapshot:
    initial_cash: Decimal
    cash: Decimal
    market_value: Decimal
    equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_fees: Decimal
    positions: tuple[Position, ...]


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    fill: Fill
    cash_after: Decimal
    realized_pnl_after: Decimal


@dataclass(slots=True)
class _MutablePosition:
    quantity: Decimal
    average_entry_price: Decimal
    remaining_entry_fees: Decimal


def _is_finite_positive(value: Decimal) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and value > ZERO


def _validate_fill(fill: Fill) -> None:
    if not isinstance(fill, Fill):
        raise TypeError("fill must be a Fill instance")
    if not isinstance(fill.fill_id, str) or not fill.fill_id.strip():
        raise ValueError("fill_id must be a non-empty string")
    if not isinstance(fill.instrument, str) or not fill.instrument.strip():
        raise ValueError("instrument must be a non-empty string")
    if not isinstance(fill.side, FillSide):
        raise ValueError("side must be BUY or SELL")
    if not _is_finite_positive(fill.quantity):
        raise ValueError("quantity must be a finite Decimal greater than zero")
    if not _is_finite_positive(fill.price):
        raise ValueError("price must be a finite Decimal greater than zero")
    if (
        not isinstance(fill.fee, Decimal)
        or not fill.fee.is_finite()
        or fill.fee < ZERO
    ):
        raise ValueError("fee must be a finite, non-negative Decimal")


class PortfolioLedger:
    """In-memory, single-currency, long-only portfolio accounting ledger."""

    def __init__(self, initial_cash: Decimal) -> None:
        if not _is_finite_positive(initial_cash):
            raise ValueError("initial_cash must be a finite Decimal greater than zero")
        self._initial_cash = initial_cash
        self._cash = initial_cash
        self._realized_pnl = ZERO
        self._total_fees = ZERO
        self._positions: dict[str, _MutablePosition] = {}
        self._marks: dict[str, Decimal] = {}
        self._fills: dict[str, Fill] = {}
        self._events: list[LedgerEvent] = []

    @property
    def events(self) -> tuple[LedgerEvent, ...]:
        """Return an immutable view of the applied fill events."""
        return tuple(self._events)

    def apply_fill(self, fill: Fill) -> bool:
        """Apply a fill once. Return False for an identical duplicate event.

        Reusing an existing fill ID with different content is an error. Failed
        validation never mutates the ledger.
        """
        _validate_fill(fill)
        previous = self._fills.get(fill.fill_id)
        if previous is not None:
            if previous == fill:
                return False
            raise ValueError("fill_id already exists with different fill data")

        position = self._positions.get(fill.instrument)
        current_quantity = position.quantity if position else ZERO

        if fill.side is FillSide.BUY:
            total_cost = fill.quantity * fill.price + fill.fee
            if total_cost > self._cash:
                raise ValueError("insufficient cash for buy including fees")

            new_quantity = current_quantity + fill.quantity
            old_notional = (
                position.average_entry_price * current_quantity if position else ZERO
            )
            new_average = (old_notional + fill.quantity * fill.price) / new_quantity
            old_entry_fees = position.remaining_entry_fees if position else ZERO

            self._cash -= total_cost
            self._positions[fill.instrument] = _MutablePosition(
                quantity=new_quantity,
                average_entry_price=new_average,
                remaining_entry_fees=old_entry_fees + fill.fee,
            )
        else:
            if position is None or fill.quantity > current_quantity:
                raise ValueError("sell quantity exceeds the open position")

            fraction_closed = fill.quantity / current_quantity
            allocated_entry_fees = (
                position.remaining_entry_fees
                if fill.quantity == current_quantity
                else position.remaining_entry_fees * fraction_closed
            )
            gross_pnl = (fill.price - position.average_entry_price) * fill.quantity
            self._realized_pnl += gross_pnl - allocated_entry_fees - fill.fee
            self._cash += fill.quantity * fill.price - fill.fee

            remaining_quantity = current_quantity - fill.quantity
            if remaining_quantity == ZERO:
                del self._positions[fill.instrument]
                self._marks.pop(fill.instrument, None)
            else:
                position.quantity = remaining_quantity
                position.remaining_entry_fees -= allocated_entry_fees

        self._total_fees += fill.fee
        self._fills[fill.fill_id] = fill
        self._events.append(
            LedgerEvent(
                fill=fill,
                cash_after=self._cash,
                realized_pnl_after=self._realized_pnl,
            )
        )
        return True

    def mark_to_market(self, instrument: str, price: Decimal) -> None:
        """Update the latest valuation price for an open position."""
        if not isinstance(instrument, str) or not instrument.strip():
            raise ValueError("instrument must be a non-empty string")
        if instrument not in self._positions:
            raise ValueError("cannot mark an instrument without an open position")
        if not _is_finite_positive(price):
            raise ValueError("mark price must be a finite Decimal greater than zero")
        self._marks[instrument] = price

    def snapshot(self) -> LedgerSnapshot:
        """Return reconciled cash, equity, P&L, fees, and sorted open positions."""
        positions = tuple(
            Position(
                instrument=name,
                quantity=position.quantity,
                average_entry_price=position.average_entry_price,
                remaining_entry_fees=position.remaining_entry_fees,
            )
            for name, position in sorted(self._positions.items())
        )
        market_value = ZERO
        unrealized_pnl = ZERO
        for name, position in self._positions.items():
            mark = self._marks.get(name, position.average_entry_price)
            market_value += position.quantity * mark
            unrealized_pnl += (
                (mark - position.average_entry_price) * position.quantity
                - position.remaining_entry_fees
            )

        equity = self._cash + market_value
        return LedgerSnapshot(
            initial_cash=self._initial_cash,
            cash=self._cash,
            market_value=market_value,
            equity=equity,
            realized_pnl=self._realized_pnl,
            unrealized_pnl=unrealized_pnl,
            total_fees=self._total_fees,
            positions=positions,
        )
