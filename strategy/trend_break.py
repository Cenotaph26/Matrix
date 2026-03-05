"""
TrendBreak Strategy — NautilusTrader implementation
1-minute trend tracking + breakout entry, trend-break exit
"""

from decimal import Decimal

from nautilus_trader.config import StrategyConfig
from nautilus_trader.core.message import Event
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.trading.strategy import Strategy


class TrendBreakConfig(StrategyConfig, frozen=True):
    """
    Configuration for TrendBreak strategy.

    Parameters
    ----------
    instrument_id : InstrumentId
        Trading instrument (e.g. BTCUSDT.BINANCE)
    bar_type : BarType
        Bar subscription type (1-minute bars)
    trade_size : Decimal
        Position size per trade
    trend_period : int
        Number of 1m bars used to define the trend channel
    break_threshold_pct : float
        Minimum % move beyond trend high/low to confirm breakout (e.g. 0.05 = 0.05%)
    stop_loss_pct : float
        Stop-loss distance as % of entry price (e.g. 0.5 = 0.5%)
    close_positions_on_stop : bool
        Whether to close open positions when the strategy stops
    """

    instrument_id: InstrumentId
    bar_type: BarType
    trade_size: Decimal
    trend_period: int = 5
    break_threshold_pct: float = 0.05   # 0.05%
    stop_loss_pct: float = 0.5          # 0.5%
    close_positions_on_stop: bool = True


class TrendBreakStrategy(Strategy):
    """
    1-minute trend-break strategy.

    Logic:
    ------
    1.  Maintain a rolling window of `trend_period` closed 1m bars.
    2.  Derive trend_high = max(highs) and trend_low = min(lows) of the window.
    3.  On each new closed bar:
        - If no position and close > trend_high * (1 + threshold) → open LONG
        - If no position and close < trend_low  * (1 - threshold) → open SHORT
        - If long position and close < trend_low  → close (trend broken down)
        - If short position and close > trend_high → close (trend broken up)
        - Stop-loss is submitted as a separate STOP_MARKET order on entry.
    """

    def __init__(self, config: TrendBreakConfig) -> None:
        super().__init__(config)
        self.instrument: Instrument | None = None
        self._bar_window: list[Bar] = []

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument not found: {self.config.instrument_id}")
            self.stop()
            return

        self.register_indicator_for_bars(self.config.bar_type, None)  # ensures subscription
        self.subscribe_bars(self.config.bar_type)
        self.log.info(
            f"TrendBreak started | period={self.config.trend_period} "
            f"threshold={self.config.break_threshold_pct}% "
            f"sl={self.config.stop_loss_pct}%"
        )

    def on_stop(self) -> None:
        self.unsubscribe_bars(self.config.bar_type)
        if self.config.close_positions_on_stop:
            self.close_all_positions(self.config.instrument_id)
            self.cancel_all_orders(self.config.instrument_id)

    def on_reset(self) -> None:
        self._bar_window.clear()

    # ── Bar handler ───────────────────────────────────────────────────────────

    def on_bar(self, bar: Bar) -> None:
        # Accumulate window
        self._bar_window.append(bar)
        if len(self._bar_window) > self.config.trend_period:
            self._bar_window.pop(0)

        # Need full window before trading
        if len(self._bar_window) < self.config.trend_period:
            self.log.debug(
                f"Warming up: {len(self._bar_window)}/{self.config.trend_period} bars"
            )
            return

        trend_high = max(float(b.high) for b in self._bar_window)
        trend_low  = min(float(b.low)  for b in self._bar_window)
        close      = float(bar.close)
        threshold  = self.config.break_threshold_pct / 100.0
        sl_pct     = self.config.stop_loss_pct / 100.0

        is_long  = self.portfolio.is_net_long(self.config.instrument_id)
        is_short = self.portfolio.is_net_short(self.config.instrument_id)
        is_flat  = self.portfolio.is_flat(self.config.instrument_id)

        # ── EXIT logic (trend reversal) ───────────────────────────────────────
        if is_long and close < trend_low:
            self.log.info(f"LONG exit — trend broken down @ {close:.4f} | trend_low={trend_low:.4f}")
            self.close_all_positions(self.config.instrument_id)
            self.cancel_all_orders(self.config.instrument_id)
            return

        if is_short and close > trend_high:
            self.log.info(f"SHORT exit — trend broken up @ {close:.4f} | trend_high={trend_high:.4f}")
            self.close_all_positions(self.config.instrument_id)
            self.cancel_all_orders(self.config.instrument_id)
            return

        # ── ENTRY logic (breakout) ────────────────────────────────────────────
        if is_flat:
            if close > trend_high * (1 + threshold):
                self.log.info(
                    f"LONG signal @ {close:.4f} | trend_high={trend_high:.4f} "
                    f"(+{threshold*100:.3f}% threshold)"
                )
                self._open_long(close, sl_pct)

            elif close < trend_low * (1 - threshold):
                self.log.info(
                    f"SHORT signal @ {close:.4f} | trend_low={trend_low:.4f} "
                    f"(-{threshold*100:.3f}% threshold)"
                )
                self._open_short(close, sl_pct)

    # ── Order helpers ─────────────────────────────────────────────────────────

    def _open_long(self, price: float, sl_pct: float) -> None:
        if not self.instrument:
            return
        qty = self.instrument.make_qty(self.config.trade_size)
        sl_price = self.instrument.make_price(price * (1 - sl_pct))

        # Market entry
        market = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=qty,
            time_in_force=TimeInForce.GTC,
        )
        # Stop-loss
        stop = self.order_factory.stop_market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.SELL,
            quantity=qty,
            trigger_price=sl_price,
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(market)
        self.submit_order(stop)

    def _open_short(self, price: float, sl_pct: float) -> None:
        if not self.instrument:
            return
        qty = self.instrument.make_qty(self.config.trade_size)
        sl_price = self.instrument.make_price(price * (1 + sl_pct))

        market = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.SELL,
            quantity=qty,
            time_in_force=TimeInForce.GTC,
        )
        stop = self.order_factory.stop_market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=qty,
            trigger_price=sl_price,
            time_in_force=TimeInForce.GTC,
        )
        self.submit_order(market)
        self.submit_order(stop)

    # ── Boilerplate ───────────────────────────────────────────────────────────

    def on_event(self, event: Event) -> None:
        pass

    def on_save(self) -> dict[str, bytes]:
        return {}

    def on_load(self, state: dict[str, bytes]) -> None:
        pass

    def on_dispose(self) -> None:
        pass
