"""Read-only Binance Spot public market-data client.

No API key, secret, account endpoint, or order endpoint is used here.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from typing import Any

from trading.execution.paper import MarketBar

_STABLE_BASES = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "USDE", "USDS", "BUSD"}
_LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")


class BinanceDataError(RuntimeError):
    """Raised when public market data is unavailable or invalid."""


class BinancePublicClient:
    """Small synchronous client for Binance public Spot REST endpoints."""

    def __init__(self, base_url: str = "https://api.binance.com", timeout: float = 12.0):
        if not base_url.startswith("https://"):
            raise ValueError("Binance base_url must use HTTPS")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _get(
        self, path: str, params: dict[str, str | int] | None = None
    ) -> Any:
        query = f"?{urlencode(params)}" if params else ""
        request = Request(
            f"{self._base_url}{path}{query}",
            headers={"Accept": "application/json", "User-Agent": "TradingPaperResearch/1.0"},
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BinanceDataError(f"Binance public request failed: {type(exc).__name__}") from exc
        if isinstance(payload, dict) and "code" in payload and "msg" in payload:
            raise BinanceDataError(f"Binance API error {payload['code']}: {payload['msg']}")
        return payload

    def top_usdt_symbols(self, limit: int = 10) -> list[str]:
        """Return active Spot USDT pairs ranked by 24h quote volume."""
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        exchange = self._get("/api/v3/exchangeInfo")
        tickers = self._get("/api/v3/ticker/24hr")
        if not isinstance(exchange, dict) or not isinstance(tickers, list):
            raise BinanceDataError("Unexpected Binance exchange metadata response")

        eligible: set[str] = set()
        for item in exchange.get("symbols", []):
            base = str(item.get("baseAsset", ""))
            if (
                item.get("status") == "TRADING"
                and item.get("quoteAsset") == "USDT"
                and item.get("isSpotTradingAllowed") is True
                and base not in _STABLE_BASES
                and base
                and not base.endswith(_LEVERAGED_SUFFIXES)
            ):
                eligible.add(str(item.get("symbol", "")))

        ranked: list[tuple[Decimal, str]] = []
        for item in tickers:
            symbol = str(item.get("symbol", ""))
            if symbol not in eligible:
                continue
            try:
                volume = Decimal(str(item["quoteVolume"]))
            except (KeyError, InvalidOperation):
                continue
            if volume.is_finite() and volume > 0:
                ranked.append((volume, symbol))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]))
        if len(ranked) < limit:
            raise BinanceDataError(
                f"Only {len(ranked)} eligible USDT Spot pairs found; {limit} required"
            )
        return [symbol for _, symbol in ranked[:limit]]

    def closed_klines(
        self, symbol: str, interval: str = "1h", limit: int = 1000
    ) -> list[MarketBar]:
        """Fetch chronological completed candles only; exclude the current open candle."""
        if not symbol or not symbol.isalnum():
            raise ValueError("symbol must contain only letters and digits")
        supported = {
            "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"
        }
        if interval not in supported:
            raise ValueError("unsupported research interval")
        if not 100 <= limit <= 1000:
            raise ValueError("limit must be between 100 and 1000")

        rows = self._get(
            "/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit}
        )
        server_time = self._get("/api/v3/time")
        if not isinstance(rows, list) or not isinstance(server_time, dict):
            raise BinanceDataError("Unexpected Binance kline/time response")
        now_ms = int(server_time["serverTime"])

        bars: list[MarketBar] = []
        previous_open_time = -1
        for row in rows:
            if not isinstance(row, list) or len(row) < 7:
                raise BinanceDataError("Malformed Binance kline row")
            open_time = int(row[0])
            close_time = int(row[6])
            if open_time <= previous_open_time:
                raise BinanceDataError("Kline timestamps are not strictly increasing")
            previous_open_time = open_time
            if close_time >= now_ms:
                continue
            try:
                open_price, high, low, close, volume = (
                    Decimal(str(row[index])) for index in (1, 2, 3, 4, 5)
                )
                bars.append(
                    MarketBar(
                        instrument=symbol,
                        timeframe=interval,
                        timestamp=datetime.fromtimestamp(open_time / 1000, tz=UTC),
                        open=open_price,
                        high=high,
                        low=low,
                        close=close,
                        volume=volume,
                        source="binance_spot",
                    )
                )
            except (InvalidOperation, ValueError, OverflowError) as exc:
                raise BinanceDataError("Invalid numeric data in Binance kline") from exc
        if len(bars) < 60:
            raise BinanceDataError(
                f"Insufficient completed candles for {symbol}: received {len(bars)}"
            )
        return bars

    def server_time_ms(self) -> int:
        """Return Binance server time for live-feed freshness checks."""
        payload = self._get("/api/v3/time")
        if not isinstance(payload, dict) or "serverTime" not in payload:
            raise BinanceDataError("Invalid Binance server-time response")
        return int(payload["serverTime"])
