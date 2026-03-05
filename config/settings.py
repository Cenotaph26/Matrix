"""
Config — loads all settings from environment variables.
Set these in Railway → Variables panel.
"""

import os
from dataclasses import dataclass


def _require(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(f"Required environment variable missing: {key}")
    return val


def _optional(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


@dataclass
class AppConfig:
    # ── Binance credentials ───────────────────────────────────────────────────
    # Set BINANCE_API_KEY and BINANCE_API_SECRET in Railway Variables.
    # NEVER hardcode credentials here.
    binance_api_key: str
    binance_api_secret: str

    # ── Account type ─────────────────────────────────────────────────────────
    # Options: SPOT | USDT_FUTURES | COIN_FUTURES
    account_type: str

    # ── Binance environment ───────────────────────────────────────────────────
    # Options: LIVE | DEMO | TESTNET
    binance_env: str

    # ── Strategy params ───────────────────────────────────────────────────────
    symbol: str
    trade_size: str
    trend_period: int
    break_threshold_pct: float
    stop_loss_pct: float

    # ── System ───────────────────────────────────────────────────────────────
    trader_id: str
    log_level: str
    port: int


def load_config() -> AppConfig:
    return AppConfig(
        # Credentials (required — must be set in Railway Variables)
        binance_api_key=_require("BINANCE_API_KEY"),
        binance_api_secret=_require("BINANCE_API_SECRET"),

        # Account & environment
        account_type=_optional("BINANCE_ACCOUNT_TYPE", "USDT_FUTURES"),
        binance_env=_optional("BINANCE_ENV", "DEMO"),   # DEMO = safe default

        # Strategy
        symbol=_optional("SYMBOL", "BTCUSDT-PERP"),
        trade_size=_optional("TRADE_SIZE", "0.001"),
        trend_period=int(_optional("TREND_PERIOD", "5")),
        break_threshold_pct=float(_optional("BREAK_THRESHOLD_PCT", "0.05")),
        stop_loss_pct=float(_optional("STOP_LOSS_PCT", "0.5")),

        # System
        trader_id=_optional("TRADER_ID", "TRENDBREAK-001"),
        log_level=_optional("LOG_LEVEL", "INFO"),
        port=int(_optional("PORT", "8000")),
    )
