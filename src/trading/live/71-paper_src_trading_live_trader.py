"""Bar-by-bar paper trader: strategy -> risk-gated paper engine -> persisted state."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from decimal import Decimal

from trading.execution.paper import (
    ExecutionCosts,
    IntentSide,
    MarketBar,
    PaperExecutionEngine,
    TradeIntent,
)
from trading.live.report import format_fill_alert
from trading.live.store import PaperStore, StoredFill
from trading.live.strategy import (
    Signal,
    StrategyParams,
    entry_levels,
    latest_signal,
    position_quantity,
)
from trading.portfolio.ledger import PortfolioLedger
from trading.risk.policy import RiskLimits

logger = logging.getLogger(__name__)

Notifier = Callable[[str], Awaitable[None]]
HISTORY_LIMIT = 400
_FILL_KINDS = {"ENTRY_FILLED", "EXIT_FILLED", "STOP_FILLED", "TARGET_FILLED"}


class PaperTrader:
    """Feeds completed bars to the engine; signals use only the newest bar."""

    def __init__(
        self,
        engine: PaperExecutionEngine,
        ledger: PortfolioLedger,
        store: PaperStore,
        params: StrategyParams,
        notify: Notifier | None = None,
    ) -> None:
        self._engine = engine
        self._ledger = ledger
        self._store = store
        self._params = params
        self._notify = notify
        self._history: dict[str, list[MarketBar]] = {}
        self._last_ts: dict[str, datetime] = {}
        self._day: object | None = None

    @classmethod
    async def create(
        cls,
        initial_cash: Decimal,
        store: PaperStore,
        costs: ExecutionCosts,
        params: StrategyParams | None = None,
        limits: RiskLimits | None = None,
        notify: Notifier | None = None,
    ) -> PaperTrader:
        """Build a trader, replaying persisted fills and stop/target levels."""
        params = params or StrategyParams()
        limits = limits or RiskLimits()
        if params.risk_per_trade_pct >= limits.max_risk_per_trade_pct:
            raise ValueError("strategy risk must stay below the risk-policy limit")
        ledger = PortfolioLedger(initial_cash)
        highest = 0
        for item in await store.load_fills():
            ledger.apply_fill(item.fill)
            suffix = item.fill.fill_id.rsplit("-", 1)[-1]
            if suffix.isdigit():
                highest = max(highest, int(suffix))
        # Entries stay disabled until the loop reads the admin pause switch.
        engine = PaperExecutionEngine(ledger, costs, limits, trading_enabled=False)
        engine.restore_fill_counter(highest)
        open_symbols = {p.instrument for p in ledger.snapshot().positions}
        for symbol, (stop, target) in (await store.load_brackets()).items():
            if symbol in open_symbols:
                engine.restore_bracket(symbol, stop, target)
        for symbol in open_symbols:
            if engine.bracket_for(symbol) is None:
                logger.error("Open paper position without stop level: %s", symbol)
        return cls(engine, ledger, store, params, notify)

    @property
    def engine(self) -> PaperExecutionEngine:
        return self._engine

    @property
    def ledger(self) -> PortfolioLedger:
        return self._ledger

    def last_bar_time(self, symbol: str) -> datetime | None:
        return self._last_ts.get(symbol)

    def set_entries_enabled(self, enabled: bool) -> None:
        self._engine.set_trading_enabled(enabled)

    async def process_bars(self, symbol: str, bars: Sequence[MarketBar]) -> int:
        """Process new completed bars for one symbol; only the last may open trades.

        The first call for a symbol only loads history, so a restart or an outage never
        trades on stale data. Returns the number of bars processed by the engine.
        """
        if symbol not in self._history:
            self._history[symbol] = list(bars[-HISTORY_LIMIT:])
            if bars:
                await self._advance(bars[-1], signal_allowed=False)
                return 1
            return 0
        last = self._last_ts.get(symbol)
        fresh = [bar for bar in bars if last is None or bar.timestamp > last]
        for index, bar in enumerate(fresh):
            self._history[symbol].append(bar)
            del self._history[symbol][:-HISTORY_LIMIT]
            await self._advance(bar, signal_allowed=index == len(fresh) - 1)
        return len(fresh)

    async def _advance(self, bar: MarketBar, *, signal_allowed: bool) -> None:
        engine = self._engine
        symbol = bar.instrument
        self._roll_period(bar)
        before = len(engine.events)
        fills = engine.process_bar(bar)
        self._last_ts[symbol] = bar.timestamp
        kinds = {
            event.fill_id: event.kind
            for event in engine.events[before:]
            if event.fill_id and event.kind in _FILL_KINDS
        }
        for fill in fills:
            item = StoredFill(fill, kinds.get(fill.fill_id, "FILL"), bar.timestamp)
            await self._store.record_fill(item)
            await self._send(format_fill_alert(item, self._ledger.snapshot().equity))
        await self._sync_bracket(symbol)
        if signal_allowed:
            self._maybe_submit(symbol, bar)

    def _roll_period(self, bar: MarketBar) -> None:
        day = bar.timestamp.date()
        if self._day != day:
            self._day = day
            self._engine.set_period_start_equity(self._ledger.snapshot().equity)

    async def _sync_bracket(self, symbol: str) -> None:
        bracket = self._engine.bracket_for(symbol)
        holding = any(p.instrument == symbol for p in self._ledger.snapshot().positions)
        if holding and bracket is not None:
            await self._store.save_bracket(symbol, bracket[0], bracket[1])
        elif not holding:
            await self._store.delete_bracket(symbol)

    def _maybe_submit(self, symbol: str, bar: MarketBar) -> None:
        engine = self._engine
        if any(i.instrument == symbol for i in engine.pending_intents):
            return
        position = next(
            (p for p in self._ledger.snapshot().positions if p.instrument == symbol), None
        )
        history = self._history[symbol]
        signal = latest_signal(history, self._params, in_position=position is not None)
        if signal is None:
            return
        stamp = bar.timestamp.strftime("%Y%m%dT%H%M")
        if signal is Signal.SELL and position is not None:
            engine.submit(TradeIntent(
                intent_id=f"{symbol}-{stamp}-sell",
                instrument=symbol,
                side=IntentSide.SELL,
                quantity=position.quantity,
                decision_bar_time=bar.timestamp,
                decision_price=bar.close,
            ))
            return
        if signal is Signal.BUY and position is None:
            levels = entry_levels(history, self._params)
            if levels is None:
                return
            stop, target = levels
            snapshot = self._ledger.snapshot()
            quantity = position_quantity(
                snapshot.equity, snapshot.cash, bar.close, stop, self._params
            )
            if quantity <= 0:
                return
            engine.submit(TradeIntent(
                intent_id=f"{symbol}-{stamp}-buy",
                instrument=symbol,
                side=IntentSide.BUY,
                quantity=quantity,
                decision_bar_time=bar.timestamp,
                decision_price=bar.close,
                stop_price=stop,
                target_price=target,
            ))

    async def record_equity(self, at: datetime) -> None:
        await self._store.record_equity(at, self._ledger.snapshot())

    async def _send(self, text: str) -> None:
        if self._notify is None:
            return
        try:
            await self._notify(text)
        except Exception as exc:  # alerts must never break trading state
            logger.warning("Paper alert delivery failed: %s", type(exc).__name__)
