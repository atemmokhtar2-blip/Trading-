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
