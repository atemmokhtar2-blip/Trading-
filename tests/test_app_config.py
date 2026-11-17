from __future__ import annotations

import pytest

from trading.app.config import ConfigurationError, Settings


def valid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db?sslmode=require")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "123456")
    monkeypatch.setenv("TRADING_MODE", "paper")


def test_loads_paper_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    valid_env(monkeypatch)
    settings = Settings.from_env()
    assert settings.trading_mode == "paper"
    assert settings.admin_telegram_id == 123456


@pytest.mark.parametrize("mode", ["live", "testnet", "production"])
def test_rejects_non_paper_mode(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    valid_env(monkeypatch)
    monkeypatch.setenv("TRADING_MODE", mode)
    with pytest.raises(ConfigurationError, match="Only TRADING_MODE=paper"):
        Settings.from_env()


@pytest.mark.parametrize("balance", ["0", "-1", "NaN", "Infinity", "not-a-number"])
def test_rejects_invalid_paper_balance(monkeypatch: pytest.MonkeyPatch, balance: str) -> None:
    valid_env(monkeypatch)
    monkeypatch.setenv("INITIAL_PAPER_BALANCE", balance)
    with pytest.raises(ConfigurationError, match="finite positive number"):
        Settings.from_env()


def test_requires_admin_id(monkeypatch: pytest.MonkeyPatch) -> None:
    valid_env(monkeypatch)
    monkeypatch.delenv("ADMIN_TELEGRAM_ID")
    with pytest.raises(ConfigurationError, match="ADMIN_TELEGRAM_ID"):
        Settings.from_env(require_telegram=True)


def test_worker_configuration_does_not_require_telegram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid_env(monkeypatch)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    monkeypatch.delenv("ADMIN_TELEGRAM_ID")
    settings = Settings.from_env()
    assert settings.telegram_bot_token is None
    assert settings.admin_telegram_id is None


def test_bot_configuration_requires_telegram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid_env(monkeypatch)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    with pytest.raises(ConfigurationError, match="TELEGRAM_BOT_TOKEN"):
        Settings.from_env(require_telegram=True)
