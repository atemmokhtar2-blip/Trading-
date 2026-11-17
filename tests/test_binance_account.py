from decimal import Decimal

import pytest

from trading.research.binance_account import (
    BinanceReadOnlyAccountClient,
    SpotAccountSnapshot,
)
from trading.research.binance_public import BinanceDataError


def test_read_only_account_client_parses_balances(monkeypatch: pytest.MonkeyPatch) -> None:
    client = BinanceReadOnlyAccountClient("public-key", "private-secret")
    monkeypatch.setattr(
        client,
        "_get_account_payload",
        lambda: {
            "accountType": "SPOT",
            "canTrade": True,
            "canWithdraw": True,
            "canDeposit": True,
            "updateTime": 123,
            "balances": [
                {"asset": "USDT", "free": "0.00", "locked": "0.00"},
                {"asset": "BTC", "free": "0.125", "locked": "0.010"},
            ],
        },
    )

    snapshot = client.account_snapshot()

    assert isinstance(snapshot, SpotAccountSnapshot)
    assert snapshot.account_type == "SPOT"
    assert snapshot.balances[0].free == Decimal("0.00")
    assert snapshot.balances[1].locked == Decimal("0.010")


def test_credentials_must_be_present_and_https_is_required() -> None:
    with pytest.raises(ValueError):
        BinanceReadOnlyAccountClient("", "secret")
    with pytest.raises(ValueError):
        BinanceReadOnlyAccountClient("key", "secret", base_url="http://localhost")


def test_invalid_account_balance_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    client = BinanceReadOnlyAccountClient("public-key", "private-secret")
    monkeypatch.setattr(
        client,
        "_get_account_payload",
        lambda: {
            "balances": [{"asset": "USDT", "free": "-1", "locked": "0"}]
        },
    )
    with pytest.raises(BinanceDataError):
        client.account_snapshot()


def test_binance_error_codes_have_clear_safe_diagnoses() -> None:
    from trading.research.binance_account import _account_error

    assert "API Secret" in _account_error(-1022).user_message
    assert "قيود IP" in _account_error(-2015).user_message
    assert _account_error(-1021).category == "timestamp"
    assert _account_error(-2015).code == -2015


def test_http_error_diagnosis_does_not_expose_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io
    from urllib.error import HTTPError

    from trading.research.binance_account import BinanceAccountError, BinancePublicClient

    client = BinanceReadOnlyAccountClient("never-log-this-key", "never-log-this-secret")
    monkeypatch.setattr(BinancePublicClient, "server_time_ms", lambda self: 123456)
    error_body = b'{"code":-2015,"msg":"Invalid API-key, IP, or permissions for action."}'

    def reject_request(*args: object, **kwargs: object) -> None:
        raise HTTPError(
            "https://api.binance.com/api/v3/account",
            401,
            "Unauthorized",
            {},
            io.BytesIO(error_body),
        )

    monkeypatch.setattr("trading.research.binance_account.urlopen", reject_request)
    with pytest.raises(BinanceAccountError) as caught:
        client.account_snapshot()

    assert caught.value.code == -2015
    assert "قيود IP" in caught.value.user_message
    assert "never-log-this-key" not in str(caught.value)
    assert "never-log-this-secret" not in str(caught.value)
