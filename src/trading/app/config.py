from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class ConfigurationError(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    telegram_bot_token: str | None = None
    admin_telegram_id: int | None = None
    trading_mode: str = "paper"
    initial_paper_balance: str = "1000"
    binance_api_key: str | None = None
    binance_api_secret: str | None = None

    @classmethod
    def from_env(cls, require_telegram: bool = False) -> Settings:
        mode = os.getenv("TRADING_MODE", "paper").strip().lower()
        if mode != "paper":
            raise ConfigurationError("Only TRADING_MODE=paper is permitted in this release")
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or None
        raw_admin_id = os.getenv("ADMIN_TELEGRAM_ID", "").strip()
        if require_telegram and not token:
            raise ConfigurationError("Missing required environment variable: TELEGRAM_BOT_TOKEN")
        if require_telegram and not raw_admin_id:
            raise ConfigurationError("Missing required environment variable: ADMIN_TELEGRAM_ID")
        try:
            admin_id = int(raw_admin_id) if raw_admin_id else None
        except ValueError as exc:
            raise ConfigurationError("ADMIN_TELEGRAM_ID must be an integer") from exc
        balance = os.getenv("INITIAL_PAPER_BALANCE", "1000").strip()
        try:
            parsed_balance = Decimal(balance)
            if not parsed_balance.is_finite() or parsed_balance <= 0:
                raise InvalidOperation
        except (InvalidOperation, ValueError) as exc:
            raise ConfigurationError(
                "INITIAL_PAPER_BALANCE must be a finite positive number"
            ) from exc
        api_key = os.getenv("BINANCE_API_KEY", "").strip() or None
        api_secret = os.getenv("BINANCE_API_SECRET", "").strip() or None
        if bool(api_key) != bool(api_secret):
            raise ConfigurationError(
                "BINANCE_API_KEY and BINANCE_API_SECRET must be configured together"
            )
        return cls(
            database_url=_required("DATABASE_URL"),
            telegram_bot_token=token,
            admin_telegram_id=admin_id,
            trading_mode=mode,
            initial_paper_balance=balance,
            binance_api_key=api_key,
            binance_api_secret=api_secret,
        )
