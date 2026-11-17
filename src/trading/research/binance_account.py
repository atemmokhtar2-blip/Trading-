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

from trading.research.binance_public import BinanceDataError, BinancePublicClient


@dataclass(frozen=True, slots=True)
class AccountBalance:
    asset: str
    free: Decimal
    locked: Decimal


@dataclass(frozen=True, slots=True)
class SpotAccountSnapshot:
    account_type: str
    update_time_ms: int
    balances: tuple[AccountBalance, ...]


class BinanceAccountError(BinanceDataError):
    """Safe, user-displayable diagnosis for a failed authenticated account read."""

    def __init__(self, category: str, user_message: str, code: int | None = None) -> None:
        super().__init__(user_message)
        self.category = category
        self.user_message = user_message
        self.code = code


def _account_error(code: int | None, http_status: int | None = None) -> BinanceAccountError:
    messages = {
        -2014: (
            "invalid_key",
            "🔑 مفتاح API غير صحيح أو بصيغة غير مدعومة. راجع API Key ونوع المفتاح.",
        ),
        -2015: (
            "key_ip_or_permission",
            "🔒 Binance رفض المفتاح: قد يكون المفتاح غير صحيح، أو عنوان IP غير مسموح، "
            "أو صلاحية القراءة غير مفعّلة. راجع API Management وقيود IP.",
        ),
        -1022: (
            "signature",
            "✍️ توقيع الطلب غير صحيح. راجع API Secret وتأكد أن المفتاح من نوع HMAC.",
        ),
        -1021: (
            "timestamp",
            "⏱️ توقيت الطلب غير متزامن مع Binance. أعد المحاولة وراجع مزامنة وقت خادم Railway.",
        ),
        -1003: (
            "rate_limit",
            "🚦 تم تجاوز حد طلبات Binance مؤقتًا. انتظر قليلًا ثم أعد المحاولة.",
        ),
        -1001: (
            "exchange_unavailable",
            "📡 خادم Binance غير متاح حاليًا. حاول مرة أخرى بعد قليل.",
        ),
        -1006: (
            "exchange_unavailable",
            "📡 لم يصل رد مؤكد من Binance. حاول مرة أخرى بعد قليل.",
        ),
        -1007: (
            "exchange_timeout",
            "⌛ انتهت مهلة استجابة Binance. حاول مرة أخرى بعد قليل.",
        ),
    }
    if code in messages:
        category, message = messages[code]
        return BinanceAccountError(category, message, code)
    if http_status == 403:
        return BinanceAccountError(
            "http_403",
            "🌐 Binance رفض الاتصال (HTTP 403). راجع قيود IP وإمكانية وصول Railway إلى Binance.",
            code,
        )
    if http_status == 429:
        return BinanceAccountError(
            "rate_limit",
            "🚦 Binance طلب تقليل عدد المحاولات. انتظر قليلًا ثم أعد المحاولة.",
            code,
        )
    suffix = f" (كود Binance: {code})" if code is not None else ""
    return BinanceAccountError(
        "exchange_error",
        f"⚠️ Binance رفض طلب قراءة الحساب بسبب غير مصنّف{suffix}. أرسل كود الخطأ للدعم.",
        code,
    )


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
        try:
            timestamp = BinancePublicClient(self._base_url, self._timeout).server_time_ms()
        except BinanceDataError as exc:
            raise BinanceAccountError(
                "connection",
                "📡 تعذر الاتصال بخدمة Binance للحصول على توقيت الخادم. "
                "تحقق من اتصال Railway وحاول مرة أخرى.",
            ) from exc

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
        except HTTPError as exc:
            code: int | None = None
            try:
                error_payload = json.loads(exc.read().decode("utf-8"))
                if isinstance(error_payload, dict) and isinstance(error_payload.get("code"), int):
                    code = error_payload["code"]
            except (json.JSONDecodeError, UnicodeDecodeError, OSError):
                pass
            raise _account_error(code, exc.code) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise BinanceAccountError(
                "connection",
                "📡 فشل الاتصال بخوادم Binance من Railway. تحقق من الشبكة ثم أعد المحاولة.",
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BinanceAccountError(
                "invalid_response",
                "⚠️ وصل رد غير مفهوم من Binance. حاول مرة أخرى، وإذا استمرت المشكلة أرسل السجلات.",
            ) from exc
        if isinstance(payload, dict) and isinstance(payload.get("code"), int):
            raise _account_error(payload["code"])
        if not isinstance(payload, dict) or "balances" not in payload:
            raise BinanceAccountError(
                "invalid_response",
                "⚠️ رد Binance لا يحتوي على بيانات الحساب المتوقعة. حاول مرة أخرى.",
            )
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
                update_time_ms=int(payload.get("updateTime", 0)),
                balances=balances,
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise BinanceDataError("Invalid fields in Binance account response") from exc
