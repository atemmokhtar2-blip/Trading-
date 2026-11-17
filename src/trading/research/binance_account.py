"""Authenticated Binance Spot account reads only.

This module intentionally exposes no order, transfer, withdrawal, or trading methods.
The API key must be configured with read-only permissions at Binance.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import socket
import ssl
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
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
    update_time_ms: int
    balances: tuple[AccountBalance, ...]


class BinanceAccountError(BinanceDataError):
    """Safe, user-displayable diagnosis for a failed authenticated account read."""

    def __init__(
        self,
        category: str,
        user_message: str,
        code: int | None = None,
        *,
        stage: str = "account",
        exception_type: str | None = None,
        reason_type: str | None = None,
        errno: int | None = None,
        http_status: int | None = None,
        elapsed_ms: int | None = None,
        host: str | None = None,
    ) -> None:
        super().__init__(user_message)
        self.category = category
        self.user_message = user_message
        self.code = code
        self.stage = stage
        self.exception_type = exception_type
        self.reason_type = reason_type
        self.errno = errno
        self.http_status = http_status
        self.elapsed_ms = elapsed_ms
        self.host = host


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
            "⏱️ توقيت الطلب غير متزامن مع Binance. أعد المحاولة وراجع "
            "مزامنة وقت خادم Railway.",
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
        return BinanceAccountError(category, message, code, stage="signed_account")
    if http_status == 403:
        return BinanceAccountError(
            "http_403",
            "🌐 Binance رفض الاتصال (HTTP 403). راجع قيود IP وإمكانية "
            "وصول Railway إلى Binance.",
            code,
            stage="signed_account",
            http_status=http_status,
        )
    if http_status == 429:
        return BinanceAccountError(
            "rate_limit",
            "🚦 Binance طلب تقليل عدد المحاولات. انتظر قليلًا ثم "
            "أعد المحاولة.",
            code,
            stage="signed_account",
            http_status=http_status,
        )
    suffix = f" (كود Binance: {code})" if code is not None else ""
    return BinanceAccountError(
        "exchange_error",
        f"⚠️ Binance رفض طلب قراءة الحساب بسبب غير مصنّف{suffix}. "
        "أرسل كود الخطأ للدعم.",
        code,
        stage="signed_account",
        http_status=http_status,
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

    def _server_time_ms(self) -> int:
        """Fetch public server time while retaining safe transport diagnostics."""
        url = f"{self._base_url}/api/v3/time"
        host = urlsplit(self._base_url).hostname
        request = Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "TradingPaperResearch/1.0"},
        )
        started = time.monotonic()
        try:
            with urlopen(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict) or "serverTime" not in payload:
                raise ValueError("missing serverTime")
            return int(payload["serverTime"])
        except HTTPError as exc:
            elapsed = round((time.monotonic() - started) * 1000)
            raise BinanceAccountError(
                "http_error",
                f"🌐 Binance ردّ برمز HTTP {exc.code} أثناء طلب التوقيت.",
                stage="server_time",
                exception_type=type(exc).__name__,
                http_status=exc.code,
                elapsed_ms=elapsed,
                host=host,
            ) from exc
        except (
            URLError,
            TimeoutError,
            socket.gaierror,
            ssl.SSLError,
            OSError,
            ValueError,
            UnicodeDecodeError,
        ) as exc:
            elapsed = round((time.monotonic() - started) * 1000)
            reason = getattr(exc, "reason", None)
            if isinstance(reason, BaseException):
                root = reason
            else:
                root = exc
            reason_type = type(root).__name__
            error_number = getattr(root, "errno", None)
            if isinstance(root, socket.gaierror):
                category = "dns"
                message = "🧭 Railway لم يستطع تحويل اسم خادم Binance إلى عنوان IP (DNS)."
            elif isinstance(root, ssl.SSLError):
                category = "tls"
                message = "🔐 فشل إنشاء اتصال TLS/SSL آمن مع Binance من Railway."
            elif isinstance(root, (TimeoutError, socket.timeout)):
                category = "timeout"
                message = "⌛ انتهت مهلة الاتصال بخادم Binance قبل وصول الرد."
            elif isinstance(root, ConnectionRefusedError):
                category = "connection_refused"
                message = "🚫 خادم الاتصال رفض اتصال Railway بخدمة Binance."
            elif isinstance(root, ValueError):
                category = "invalid_response"
                message = "⚠️ تم الاتصال، لكن رد توقيت Binance غير صالح أو غير مفهوم."
            else:
                category = "network"
                message = (
                    "📡 فشل اتصال الشبكة بين Railway وBinance. "
                    "التشخيص التفصيلي موجود في سجلات Railway."
                )
            raise BinanceAccountError(
                category,
                message,
                stage="server_time",
                exception_type=type(exc).__name__,
                reason_type=reason_type,
                errno=error_number if isinstance(error_number, int) else None,
                elapsed_ms=elapsed,
                host=host,
            ) from exc

    def _get_account_payload(self) -> dict[str, Any]:
        """Call the signed GET /api/v3/account endpoint; no other private route exists."""
        timestamp = self._server_time_ms()
        params = {"recvWindow": 5000, "timestamp": timestamp}
        query = urlencode(params)
        signature = hmac.new(self._api_secret, query.encode("utf-8"), hashlib.sha256).hexdigest()
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
                "📡 فشل الاتصال بخوادم Binance أثناء قراءة الحساب. راجع سجلات Railway.",
                stage="signed_account",
                exception_type=type(exc).__name__,
                reason_type=type(getattr(exc, "reason", exc)).__name__,
                errno=getattr(getattr(exc, "reason", exc), "errno", None),
                host=urlsplit(self._base_url).hostname,
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BinanceAccountError(
                "invalid_response",
                "⚠️ وصل رد غير مفهوم من Binance أثناء قراءة الحساب.",
                stage="signed_account",
                exception_type=type(exc).__name__,
                host=urlsplit(self._base_url).hostname,
            ) from exc
        if isinstance(payload, dict) and isinstance(payload.get("code"), int):
            raise _account_error(payload["code"])
        if not isinstance(payload, dict) or "balances" not in payload:
            raise BinanceAccountError(
                "invalid_response",
                "⚠️ رد Binance لا يحتوي على بيانات الحساب المتوقعة.",
                stage="signed_account",
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
