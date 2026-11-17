"""Authenticated Binance Spot account reads only.

This module intentionally exposes no order, transfer, withdrawal, or trading methods.
The API key must be configured with read-only permissions at Binance.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from trading.research.binance_public import BinanceDataError


@dataclass(frozen=True, slots=True)
class AccountBalance:
    asset: str
    free: Decimal
    locked: Decimal


@dataclass(frozen=True, slots=True)
class SpotAccountSnapshot:
    account_type: str
    can_trade: bool
    can_withdraw: bool
    can_deposit: bool
    update_time_ms: int
    balances: tuple[AccountBalance, ...]


class BinanceReadOnlyAccountClient:
    """Minimal HMAC-signed GET client limited to Binance account information."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = "https://api.binance.com",
        timeout: float = 12.0,
    ) -> None:
        if not api_key.strip() or not api_secret.strip():
            raise ValueError("Binance read-only API credentials must both be configured")
        if not base_url.startswith("https://"):
            raise ValueError("Binance base_url must use HTTPS")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._api_key = api_key.strip()
        self._api_secret = api_secret.strip().encode("utf-8")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _get_account_payload(self) -> dict[str, Any]:
        """Call the signed GET /api/v3/account endpoint; no other private route exists."""
        from trading.research.binance_public import BinancePublicClient

        timestamp = BinancePublicClient(self._base_url, self._timeout).server_time_ms()
        params = {"recvWindow": 5000, "timestamp": timestamp}
        query = urlencode(params)
        signature = hmac.new(
            self._api_secret, query.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        request = Request(
            f"{self._base_url}/api/v3/account?{query}&signature={signature}",
            headers={
                "Accept": "application/json",
                "X-MBX-APIKEY": self._api_key,
                "User-Agent": "TradingPaperResearch/1.0",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            # Never include the request URL, headers, API key, or secret in errors.
            raise BinanceDataError(
                f"Binance authenticated read failed: {type(exc).__name__}"
            ) from exc
        if not isinstance(payload, dict) or "balances" not in payload:
            raise BinanceDataError("Unexpected Binance account response")
        return payload

    def account_snapshot(self) -> SpotAccountSnapshot:
        """Read account permissions and balances; does not submit any exchange action."""
        payload = self._get_account_payload()
        try:
            balances = tuple(
                AccountBalance(
                    asset=str(item["asset"]),
                    free=Decimal(str(item["free"])),
                    locked=Decimal(str(item["locked"])),
                )
                for item in payload["balances"]
            )
            if any(
                not item.asset
                or not item.free.is_finite()
                or not item.locked.is_finite()
                or item.free < 0
                or item.locked < 0
                for item in balances
            ):
                raise ValueError("invalid balance")
            return SpotAccountSnapshot(
                account_type=str(payload.get("accountType", "SPOT")),
                can_trade=bool(payload.get("canTrade", False)),
                can_withdraw=bool(payload.get("canWithdraw", False)),
                can_deposit=bool(payload.get("canDeposit", False)),
                update_time_ms=int(payload.get("updateTime", 0)),
                balances=balances,
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise BinanceDataError("Invalid fields in Binance account response") from exc
