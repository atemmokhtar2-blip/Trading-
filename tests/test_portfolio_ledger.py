from decimal import Decimal

import pytest

from trading.portfolio.ledger import Fill, FillSide, PortfolioLedger

D = Decimal


def buy(
    fill_id: str = "buy-1",
    *,
    instrument: str = "EURUSD",
    quantity: Decimal = D("2"),
    price: Decimal = D("100"),
    fee: Decimal = D("1"),
) -> Fill:
    return Fill(fill_id, instrument, FillSide.BUY, quantity, price, fee)


def sell(
    fill_id: str = "sell-1",
    *,
    instrument: str = "EURUSD",
    quantity: Decimal = D("2"),
    price: Decimal = D("110"),
    fee: Decimal = D("1"),
) -> Fill:
    return Fill(fill_id, instrument, FillSide.SELL, quantity, price, fee)


def test_buy_updates_cash_position_and_equity() -> None:
    ledger = PortfolioLedger(D("1000"))

    assert ledger.apply_fill(buy()) is True
    state = ledger.snapshot()

    assert state.cash == D("799")
    assert state.market_value == D("200")
    assert state.equity == D("999")
    assert state.total_fees == D("1")
    assert state.positions[0].quantity == D("2")
    assert state.positions[0].average_entry_price == D("100")


def test_mark_to_market_updates_unrealized_pnl_and_equity() -> None:
    ledger = PortfolioLedger(D("1000"))
    ledger.apply_fill(buy())
    ledger.mark_to_market("EURUSD", D("110"))

    state = ledger.snapshot()

    assert state.market_value == D("220")
    assert state.unrealized_pnl == D("19")
    assert state.equity == D("1019")


def test_full_sell_realizes_profit_net_of_entry_and_exit_fees() -> None:
    ledger = PortfolioLedger(D("1000"))
    ledger.apply_fill(buy())
    ledger.apply_fill(sell())

    state = ledger.snapshot()

    assert state.cash == D("1018")
    assert state.market_value == D("0")
    assert state.equity == D("1018")
    assert state.realized_pnl == D("18")
    assert state.unrealized_pnl == D("0")
    assert state.total_fees == D("2")
    assert state.positions == ()


def test_partial_sell_allocates_entry_fee_proportionally() -> None:
    ledger = PortfolioLedger(D("1000"))
    ledger.apply_fill(buy(quantity=D("4"), fee=D("4")))
    ledger.apply_fill(sell(quantity=D("1"), price=D("110"), fee=D("1")))

    state = ledger.snapshot()

    assert state.positions[0].quantity == D("3")
    assert state.positions[0].remaining_entry_fees == D("3")
    assert state.realized_pnl == D("6.0")
    assert state.cash == D("685")


def test_average_entry_price_is_weighted_across_buys() -> None:
    ledger = PortfolioLedger(D("1000"))
    ledger.apply_fill(buy(quantity=D("1"), price=D("100"), fee=D("0")))
    ledger.apply_fill(
        buy("buy-2", quantity=D("3"), price=D("120"), fee=D("0"))
    )

    position = ledger.snapshot().positions[0]
    assert position.quantity == D("4")
    assert position.average_entry_price == D("115")


def test_duplicate_identical_fill_is_ignored_exactly_once() -> None:
    ledger = PortfolioLedger(D("1000"))
    fill = buy()

    assert ledger.apply_fill(fill) is True
    before = ledger.snapshot()
    assert ledger.apply_fill(fill) is False
    after = ledger.snapshot()

    assert after == before
    assert len(ledger.events) == 1


def test_duplicate_fill_id_with_different_payload_is_rejected() -> None:
    ledger = PortfolioLedger(D("1000"))
    ledger.apply_fill(buy())

    with pytest.raises(ValueError, match="different fill data"):
        ledger.apply_fill(buy(quantity=D("1")))

    assert len(ledger.events) == 1


def test_cannot_sell_more_than_open_quantity() -> None:
    ledger = PortfolioLedger(D("1000"))
    ledger.apply_fill(buy())

    with pytest.raises(ValueError, match="exceeds"):
        ledger.apply_fill(sell(quantity=D("3")))

    assert ledger.snapshot().positions[0].quantity == D("2")
    assert len(ledger.events) == 1


def test_cannot_buy_without_enough_cash_including_fee() -> None:
    ledger = PortfolioLedger(D("100"))

    with pytest.raises(ValueError, match="insufficient cash"):
        ledger.apply_fill(buy(quantity=D("1"), price=D("100"), fee=D("1")))

    assert ledger.snapshot().cash == D("100")
    assert ledger.events == ()


def test_invalid_fill_values_are_rejected_without_mutation() -> None:
    ledger = PortfolioLedger(D("1000"))
    invalid = Fill("bad", "EURUSD", FillSide.BUY, D("NaN"), D("10"), D("0"))

    with pytest.raises(ValueError, match="quantity"):
        ledger.apply_fill(invalid)

    assert ledger.snapshot().cash == D("1000")
    assert ledger.events == ()


@pytest.mark.parametrize("cash", [D("0"), D("-1"), D("NaN"), D("Infinity")])
def test_initial_cash_must_be_finite_and_positive(cash: Decimal) -> None:
    with pytest.raises(ValueError):
        PortfolioLedger(cash)


def test_mark_requires_an_open_position_and_valid_price() -> None:
    ledger = PortfolioLedger(D("1000"))

    with pytest.raises(ValueError, match="without an open position"):
        ledger.mark_to_market("EURUSD", D("10"))

    ledger.apply_fill(buy())
    with pytest.raises(ValueError, match="mark price"):
        ledger.mark_to_market("EURUSD", D("NaN"))


def test_ledger_equity_reconciles_after_partial_and_full_close() -> None:
    ledger = PortfolioLedger(D("2000"))
    ledger.apply_fill(buy(quantity=D("5"), price=D("20"), fee=D("2")))
    ledger.mark_to_market("EURUSD", D("24"))

    open_state = ledger.snapshot()
    assert open_state.equity == (
        open_state.initial_cash
        + open_state.realized_pnl
        + open_state.unrealized_pnl
    )

    ledger.apply_fill(sell(quantity=D("2"), price=D("23"), fee=D("1")))
    middle_state = ledger.snapshot()
    assert middle_state.equity == (
        middle_state.initial_cash
        + middle_state.realized_pnl
        + middle_state.unrealized_pnl
    )

    ledger.apply_fill(sell("sell-rest", quantity=D("3"), price=D("22"), fee=D("1")))
    closed_state = ledger.snapshot()
    assert closed_state.equity == (
        closed_state.initial_cash + closed_state.realized_pnl
    )
    assert closed_state.positions == ()
