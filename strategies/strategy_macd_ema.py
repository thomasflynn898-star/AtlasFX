
from __future__ import annotations
from datetime import datetime
from typing import Optional
import pandas as pd
from indicators.technical import ema, atr, macd
from logs.logger import get_logger
from strategies.base import BaseStrategy, StrategyMetadata, TradeSignal

log = get_logger(__name__)

class MACDEMAStrategy(BaseStrategy):
    """
    MACD + 200 EMA Trend Strategy.

    Rules:
        - 200 EMA defines trend direction (price above = bullish bias)
        - MACD crossover in trend direction triggers entry
        - Stop loss: 1.5x ATR below/above entry
        - Take profit: 3x ATR (2:1 R:R minimum)
        - No trades on Friday

    This strategy has NOT been validated for live trading.
    """

    METADATA = StrategyMetadata(
        strategy_id="MACD_EMA_TREND_V1",
        name="MACD + 200 EMA Trend",
        version="1.0.0",
        description="MACD crossover with 200 EMA trend filter. ATR-based SL/TP.",
        instruments=["EUR_USD","GBP_USD","USD_JPY","XAU_USD"],
        timeframes=["D","H4"],
        min_history_bars=220,
    )

    def __init__(
        self,
        ema_trend_period: int = 200,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        atr_period: int = 14,
        sl_atr_mult: float = 1.5,
        tp_atr_mult: float = 3.0,
        pip_size: float = 0.0001,
    ) -> None:
        super().__init__()
        self.ema_trend_period = ema_trend_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal_period = macd_signal
        self.atr_period = atr_period
        self.sl_atr_mult = sl_atr_mult
        self.tp_atr_mult = tp_atr_mult
        self.pip_size = pip_size

    def generate_signal(
        self,
        data: pd.DataFrame,
        instrument: str,
        timeframe: str,
        current_bar_index: int = -1,
    ) -> Optional[TradeSignal]:
        if not self.validate_data(data):
            return None

        close = data["Close"]
        high  = data["High"]
        low   = data["Low"]

        # Friday filter
        bar_time = data.index[-1]
        if hasattr(bar_time, "weekday") and bar_time.weekday() == 4:
            return None

        # Indicators
        trend_ema  = ema(close, self.ema_trend_period)
        macd_line, signal_line, _ = macd(close, self.macd_fast, self.macd_slow, self.macd_signal_period)
        atr_series = atr(high, low, close, self.atr_period)

        # Need at least 2 bars of MACD to detect crossover
        if len(macd_line) < 2:
            return None

        current_atr   = atr_series.iloc[-1]
        current_ema   = trend_ema.iloc[-1]
        current_close = close.iloc[-1]

        if pd.isna(current_atr) or pd.isna(current_ema) or current_atr <= 0:
            return None

        # MACD crossover detection (previous bar vs current bar)
        macd_prev   = macd_line.iloc[-2]
        macd_curr   = macd_line.iloc[-1]
        signal_prev = signal_line.iloc[-2]
        signal_curr = signal_line.iloc[-1]

        bullish_cross = (macd_prev < signal_prev) and (macd_curr > signal_curr)
        bearish_cross = (macd_prev > signal_prev) and (macd_curr < signal_curr)

        above_ema = current_close > current_ema
        below_ema = current_close < current_ema

        direction = None
        if bullish_cross and above_ema:
            direction = "BUY"
        elif bearish_cross and below_ema:
            direction = "SELL"

        if direction is None:
            return None

        entry = current_close
        sl_dist = current_atr * self.sl_atr_mult
        tp_dist = current_atr * self.tp_atr_mult

        if direction == "BUY":
            stop_loss   = entry - sl_dist
            take_profit = entry + tp_dist
        else:
            stop_loss   = entry + sl_dist
            take_profit = entry - tp_dist

        rr = tp_dist / sl_dist
        if rr < 1.5:
            return None

        # Confidence: higher when price is well clear of EMA
        ema_distance_pct = abs(current_close - current_ema) / current_ema * 100
        confidence = min(0.5 + ema_distance_pct * 0.1, 0.85)

        try:
            signal = TradeSignal(
                strategy_id=self.METADATA.strategy_id,
                instrument=instrument,
                direction=direction,
                entry_price=round(entry, 5),
                stop_loss=round(stop_loss, 5),
                take_profit=round(take_profit, 5),
                confidence=round(confidence, 2),
                timeframe=timeframe,
                timestamp=bar_time if isinstance(bar_time, datetime) else datetime.utcnow(),
                metadata={
                    "atr": round(current_atr, 5),
                    "ema200": round(current_ema, 5),
                    "macd": round(macd_curr, 6),
                    "rr": round(rr, 2),
                },
            )
        except ValueError as e:
            log.debug("signal_construction_failed", error=str(e))
            return None

        log.debug("signal_generated", direction=direction,
                  entry=round(entry,5), sl=round(stop_loss,5),
                  tp=round(take_profit,5), rr=round(rr,2))
        return signal
