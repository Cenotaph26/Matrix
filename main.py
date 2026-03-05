"""
TrendBreak Bot — Railway entry point
Runs NautilusTrader TradingNode + FastAPI health server side-by-side
"""

import asyncio
import logging
import os
import threading
from decimal import Decimal

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# ── NautilusTrader imports ────────────────────────────────────────────────────
from nautilus_trader.adapters.binance import (
    BINANCE,
    BinanceAccountType,
    BinanceDataClientConfig,
    BinanceExecClientConfig,
    BinanceLiveDataClientFactory,
    BinanceLiveExecClientFactory,
)
from nautilus_trader.adapters.binance.common.enums import BinanceEnvironment
from nautilus_trader.config import (
    InstrumentProviderConfig,
    LiveExecEngineConfig,
    LoggingConfig,
    TradingNodeConfig,
)
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import InstrumentId, TraderId

from config.settings import load_config
from strategy.trend_break import TrendBreakConfig, TrendBreakStrategy

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── FastAPI health server ─────────────────────────────────────────────────────
# Railway requires an HTTP server to mark the service as healthy.
# This minimal server runs in a background thread.
health_app = FastAPI(title="TrendBreak Health")
_node_ref: TradingNode | None = None


@health_app.get("/health")
def health():
    is_running = _node_ref is not None and _node_ref.is_running
    return JSONResponse({"ok": True, "trading": is_running})


@health_app.get("/")
def root():
    return JSONResponse({"service": "TrendBreak Bot", "status": "running"})


def _run_health_server(port: int) -> None:
    uvicorn.run(health_app, host="0.0.0.0", port=port, log_level="warning")


# ── TradingNode setup ─────────────────────────────────────────────────────────

def build_node(cfg) -> TradingNode:
    # Resolve account type enum
    account_type_map = {
        "SPOT": BinanceAccountType.SPOT,
        "USDT_FUTURES": BinanceAccountType.USDT_FUTURES,
        "COIN_FUTURES": BinanceAccountType.COIN_FUTURES,
    }
    account_type = account_type_map.get(cfg.account_type.upper(), BinanceAccountType.USDT_FUTURES)

    # Resolve environment enum
    env_map = {
        "LIVE": BinanceEnvironment.LIVE,
        "DEMO": BinanceEnvironment.DEMO,
        "TESTNET": BinanceEnvironment.TESTNET,
    }
    binance_env = env_map.get(cfg.binance_env.upper(), BinanceEnvironment.DEMO)

    instrument_id = InstrumentId.from_str(f"{cfg.symbol}.{BINANCE}")

    node_config = TradingNodeConfig(
        trader_id=TraderId(cfg.trader_id),
        logging=LoggingConfig(
            log_level=cfg.log_level,
            log_colors=False,   # disable ANSI in Railway logs
            use_pyo3=True,
        ),
        exec_engine=LiveExecEngineConfig(
            reconciliation=True,
            reconciliation_lookback_mins=1440,
            graceful_shutdown_on_exception=True,
        ),
        data_clients={
            BINANCE: BinanceDataClientConfig(
                api_key=cfg.binance_api_key,
                api_secret=cfg.binance_api_secret,
                account_type=account_type,
                environment=binance_env,
                instrument_provider=InstrumentProviderConfig(load_all=False),
            ),
        },
        exec_clients={
            BINANCE: BinanceExecClientConfig(
                api_key=cfg.binance_api_key,
                api_secret=cfg.binance_api_secret,
                account_type=account_type,
                environment=binance_env,
                instrument_provider=InstrumentProviderConfig(load_all=False),
                max_retries=3,
            ),
        },
        timeout_connection=30.0,
        timeout_reconciliation=10.0,
        timeout_portfolio=10.0,
        timeout_disconnection=10.0,
        timeout_post_stop=5.0,
    )

    node = TradingNode(config=node_config)

    # Determine bar type string based on account type
    suffix = "EXTERNAL"
    bar_type_str = f"{cfg.symbol}.{BINANCE}-1-MINUTE-LAST-{suffix}"

    strat_config = TrendBreakConfig(
        order_id_tag="TB001",
        instrument_id=instrument_id,
        bar_type=bar_type_str,
        trade_size=Decimal(cfg.trade_size),
        trend_period=cfg.trend_period,
        break_threshold_pct=cfg.break_threshold_pct,
        stop_loss_pct=cfg.stop_loss_pct,
        close_positions_on_stop=True,
    )

    strategy = TrendBreakStrategy(config=strat_config)
    node.trader.add_strategy(strategy)
    node.add_data_client_factory(BINANCE, BinanceLiveDataClientFactory)
    node.add_exec_client_factory(BINANCE, BinanceLiveExecClientFactory)
    node.build()

    return node


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    cfg = load_config()

    logger.info(f"Starting TrendBreak Bot | {cfg.symbol} | env={cfg.binance_env}")
    logger.info(f"Strategy: period={cfg.trend_period} | threshold={cfg.break_threshold_pct}% | sl={cfg.stop_loss_pct}%")

    # Start health server in background thread (Railway requirement)
    health_thread = threading.Thread(
        target=_run_health_server,
        args=(cfg.port,),
        daemon=True,
    )
    health_thread.start()
    logger.info(f"Health server started on :{cfg.port}")

    # Build and run trading node
    global _node_ref
    node = build_node(cfg)
    _node_ref = node

    try:
        node.run()
    except KeyboardInterrupt:
        logger.info("Interrupted — shutting down...")
    finally:
        node.dispose()
        logger.info("Node disposed. Goodbye.")


if __name__ == "__main__":
    main()
