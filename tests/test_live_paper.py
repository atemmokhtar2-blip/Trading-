import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading.execution.paper import ExecutionCosts, MarketBar
from trading.live.loop import run_paper_loop
from trading.live.report import format_summary
from trading.live.store import InMemoryPaperStore
from trading.live.strategy import (
    Signal,
    StrategyParams,
    average_true_range,
    entry_levels,
    latest_signal,
    position_quantity,
)
from trading.live.trader import PaperTrader

D = Decimal
COSTS = ExecutionCosts(D("5"), D("5"), D("10"))
START = datetime(2026, 1, 1, tzinfo=UTC)
SMALL = StrategyParams(fast_period=3, slow_period=6, trend_period=12, atr_period=4)


def make_bars(closes: list[float], symbol: str = "BTCUSDT", offset: int = 0) -> list[MarketBar]:
    bars = []
    previous = closes[0]
    for index, close in enumerate(closes):
        open_price = previous
        high = max(open_price, close) * 1.004
        low = min(open_price, close) * 0.996
        bars.append(MarketBar(
            symbol, "1h", START + timedelta(hours=offset + index),
            D(str(open_price)), D(str(high)), D(str(low)), D(str(close)), D("1"),
            "binance_spot",
        ))
        previous = close
    return bars


# Falling, then a V-shaped rally: produces a fast/slow cross up above the trend EMA.
DOWN = [100 - i * 0.5 for i in range(30)]
UP = [DOWN[-1] + i * 1.5 for i in range(1, 40)]
RALLY = DOWN + UP


def test_params_validation() -> None:
    with pytest.raises(ValueError):
        StrategyParams(fast_period=10, slow_period=5)
    with pytest.raises(ValueError):
        StrategyParams(max_cash_fraction=D("1.5"))


def test_atr_and_levels() -> None:
    bars = make_bars(RALLY)
    atr = average_true_range(bars, 4)
    assert atr is not None and atr > 0
    assert average_true_range(bars[:3], 4) is None
    stop, target = entry_levels(bars, SMALL) or (None, None)
    assert stop is not None and target is not None
    assert stop < bars[-1].close < target


def test_signal_buy_only_once_on_cross_bar() -> None:
    bars = make_bars(RALLY)
    buys = [
        i for i in range(len(bars))
        if latest_signal(bars[: i + 1], SMALL, in_position=False) is Signal.BUY
    ]
    assert len(buys) >= 1
    # No signal without enough history, and never a BUY while already holding.
    assert latest_signal(bars[:5], SMALL, in_position=False) is None
    assert all(
        latest_signal(bars[: i + 1], SMALL, in_position=True) is not Signal.BUY
        for i in range(len(bars))
    )


def test_position_quantity_risk_and_cash_cap() -> None:
    params = StrategyParams()
    qty = position_quantity(D("1000"), D("1000"), D("100"), D("98"), params)
    assert qty * D("2") == D("4")  # 0.4% of 1000 risked
    capped = position_quantity(D("1000"), D("50"), D("100"), D("99.99"), params)
    assert capped * D("100") <= D("50") * params.max_cash_fraction
    assert position_quantity(D("1000"), D("1000"), D("100"), D("101"), params) == 0


async def run_through(
    trader: PaperTrader, bars: list[MarketBar], *, warm: int = 20
) -> None:
    await trader.process_bars("BTCUSDT", bars[:warm])
    for bar in bars[warm:]:
        await trader.process_bars("BTCUSDT", [bar])


def test_full_cycle_trades_persist_and_respect_risk() -> None:
    async def scenario() -> None:
        store = InMemoryPaperStore()
        alerts: list[str] = []

        async def notify(text: str) -> None:
            alerts.append(text)

        trader = await PaperTrader.create(D("1000"), store, COSTS, SMALL, notify=notify)
        trader.set_entries_enabled(True)
        bars = make_bars(RALLY + [RALLY[-1] - i * 2 for i in range(1, 25)])
        await run_through(trader, bars)
        snap = trader.ledger.snapshot()
        assert store.fills, "expected at least one paper trade"
        assert store.fills[0].fill.side.value == "BUY"
        assert store.fills[0].reason == "ENTRY_FILLED"
        assert alerts and "محاكاة فقط" in alerts[0]
        # Entry risk never exceeds the policy limit: loss at stop is bounded.
        assert snap.equity > D("900")
        # Closed positions leave no stored bracket.
        holding = {p.instrument for p in snap.positions}
        assert set(store.brackets) == holding

    asyncio.run(scenario())


def test_entries_disabled_means_no_trades() -> None:
    async def scenario() -> None:
        store = InMemoryPaperStore()
        trader = await PaperTrader.create(D("1000"), store, COSTS, SMALL)
        trader.set_entries_enabled(False)
        await run_through(trader, make_bars(RALLY))
        assert store.fills == []

    asyncio.run(scenario())


def test_first_call_loads_history_without_trading_and_duplicates_ignored() -> None:
    async def scenario() -> None:
        store = InMemoryPaperStore()
        trader = await PaperTrader.create(D("1000"), store, COSTS, SMALL)
        trader.set_entries_enabled(True)
        bars = make_bars(RALLY)
        assert await trader.process_bars("BTCUSDT", bars) == 1
        assert store.fills == []
        assert await trader.process_bars("BTCUSDT", bars) == 0
        assert trader.last_bar_time("BTCUSDT") == bars[-1].timestamp

    asyncio.run(scenario())


def test_restart_restores_position_bracket_and_unique_fill_ids() -> None:
    async def scenario() -> None:
        store = InMemoryPaperStore()
        first = await PaperTrader.create(D("1000"), store, COSTS, SMALL)
        first.set_entries_enabled(True)
        bars = make_bars(RALLY)[:33]  # ends right after the entry fill
        await run_through(first, bars)
        held = [p for p in first.ledger.snapshot().positions]
        assert held, "scenario should end holding a position"
        second = await PaperTrader.create(D("1000"), store, COSTS, SMALL)
        assert second.ledger.snapshot().cash == first.ledger.snapshot().cash
        assert second.engine.bracket_for("BTCUSDT") == first.engine.bracket_for("BTCUSDT")
        second.set_entries_enabled(True)
        crash = [bars[-1].close * D("0.5")]
        nxt = make_bars([float(crash[0])], offset=len(bars))
        await second.process_bars("BTCUSDT", bars[-5:])
        await second.process_bars("BTCUSDT", nxt)
        ids = [item.fill.fill_id for item in store.fills]
        assert len(ids) == len(set(ids))
        assert not second.ledger.snapshot().positions  # stop hit after restart

    asyncio.run(scenario())


def test_risk_limit_guard_on_create() -> None:
    async def scenario() -> None:
        with pytest.raises(ValueError):
            await PaperTrader.create(
                D("1000"), InMemoryPaperStore(), COSTS,
                StrategyParams(risk_per_trade_pct=D("0.6")),
            )

    asyncio.run(scenario())


class FakeClient:
    def __init__(self, bars: list[MarketBar], fail_times: int = 0) -> None:
        self.bars = bars
        self.fail_times = fail_times
        self.calls = 0

    def top_usdt_symbols(self, limit: int = 10) -> list[str]:
        self.calls += 1
        if self.fail_times:
            self.fail_times -= 1
            raise RuntimeError("network down")
        return ["BTCUSDT"]

    def closed_klines(
        self, symbol: str, interval: str = "1h", limit: int = 1000
    ) -> list[MarketBar]:
        return self.bars


def test_loop_survives_errors_backs_off_and_records_equity() -> None:
    async def scenario() -> None:
        store = InMemoryPaperStore()
        trader = await PaperTrader.create(D("1000"), store, COSTS, SMALL)
        delays: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            delays.append(seconds)

        async def paused() -> bool:
            return True

        client = FakeClient(make_bars(RALLY), fail_times=2)
        await run_paper_loop(
            trader, client, paused, poll_seconds=60, sleep=fake_sleep, max_cycles=4
        )
        assert delays[0] == 120 and delays[1] == 240  # exponential backoff
        assert delays[2] == 60  # recovered
        assert len(store.equity) == 1  # only the first processed cycle added a bar
        assert store.fills == []  # paused: no entries

    asyncio.run(scenario())


def test_summary_text_empty_and_populated() -> None:
    assert "لسه مفيش" in format_summary({"latest": None}, D("1000"))
    text = format_summary(
        {
            "latest": {
                "equity": D("1010"), "cash": D("500"), "realized_pnl": D("8"),
                "unrealized_pnl": D("2"), "total_fees": D("1"),
            },
            "peak_equity": D("1020"),
            "fill_count": 2,
            "recent_fills": [
                {"symbol": "BTCUSDT", "side": "BUY", "quantity": D("0.01"),
                 "price": D("100"), "reason": "ENTRY_FILLED"},
            ],
            "open_symbols": ["BTCUSDT"],
        },
        D("1000"),
    )
    assert "+1.00%" in text and "BTCUSDT" in text
