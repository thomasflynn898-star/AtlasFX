"""
strategies/strategy_london_breakout.py
───────────────────────────────────────
London Breakout Strategy.

Concept:
    The Asian session (00:00–07:00 UTC) establishes a range as price
    consolidates in low-liquidity conditions. When the London session
    opens (07:00 UTC), institutional order flow frequently breaks out
    of this range with momentum. We trade that breakout with a defined
    stop below/above the Asian range and a 2:1 reward target.

Entry rules:
    - Calculate the high and low of the Asian session (00:00–07:00 UTC)
    - At the London open (07:00–09:00 UTC window), if price closes above
      the Asian high: BUY signal
    - If price closes below the Asian low: SELL signal
    - Minimum range size filter: range must be >= min_range_pips
    - Maximum range size filter: range must be <= max_range_pips
      (very wide ranges suggest news events — avoid)

Stop loss:
    - BUY: stop at Asian session low (minus buffer)
    - SELL: stop at Asian session high (plus buffer)

Take profit:
    - Default 2.0x the risk distance (2:1 R:R)

Filters:
    - Day of week: skip Mondays (gaps) and Fridays (closes early)
    - Minimum ATR filter: avoid very low volatility days

IMPORTANT: This strategy has been implemented but has NOT been validated
against live broker data. The backtest results are simulated approximations
only. Do not trade live without completing the full validation pipeline.

This strategy is designed for H1 timeframe data.
On daily data it operates as a simplified daily breakout variant.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from indicators.technical import atr, highest, lowest
from logs.logger import get_logger
from strategies.base import BaseStrategy, StrategyMetadata, TradeSignal

log = get_logger(__name__)


class LondonBreakoutStrategy(BaseStrategy):
    """
    London/Asian Range Breakout Strategy.

    Parameters:
        lookback_bars: Bars to look back for the Asian range (default 7 for H1)
        min_range_pips: Minimum Asian range size in pips (default 10)
        max_range_pips: Maximum Asian range size in pips (default 80)
        rr_ratio: Take profit as multiple of risk (default 2.0)
        sl_buffer_pips: Extra buffer beyond Asian range for stop (default 2)
        atr_period: ATR period for volatility filter (default 14)
        atr_min_multiplier: Minimum ATR as multiple of pip (default 5)
        pip_size: Pip size for the instrument (default 0.0001)
    """

    METADATA = StrategyMetadata(
        strategy_id="LONDON_BREAKOUT_V1",
        name="London/Asian Range Breakout",
        version="1.0.0",
        description=(
            "Trades the breakout of the Asian session range at London open. "
            "Entry on close above/below range. 2:1 R:R default. "
            "NOT validated for live trading."
        ),
        instruments=["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD"],
        timeframes=["H1", "D"],
        min_history_bars=30,
    )

    def __init__(
        self,
        lookback_bars: int = 7,
        min_range_pips: float = 10.0,
        max_range_pips: float = 80.0,
        rr_ratio: float = 2.0,
        sl_buffer_pips: float = 2.0,
        atr_period: int = 14,
        pip_size: float = 0.0001,
    ) -> None:
        super().__init__()
        self.lookback_bars = lookback_bars
        self.min_range_pips = min_range_pips
        self.max_range_pips = max_range_pips
        self.rr_ratio = rr_ratio
        self.sl_buffer_pips = sl_buffer_pips
        self.atr_period = atr_period
        self.pip_size = pip_size

        self._min_range = min_range_pips * pip_size
        self._max_range = max_range_pips * pip_size
        self._sl_buffer = sl_buffer_pips * pip_size

    def generate_signal(
        self,
        data: pd.DataFrame,
        instrument: str,
        timeframe: str,
        current_bar_index: int = -1,
    ) -> Optional[TradeSignal]:
        """
        Evaluate the current bar for a London Breakout signal.

        For daily data: uses a simplified N-bar lookback for the range.
        For H1 data: uses the lookback_bars to approximate the Asian session.

        Returns a TradeSignal if conditions are met, None otherwise.
        """
        if not self.validate_data(data):
            return None

        # Work with the most recent bars
        recent = data.iloc[-max(self.lookback_bars + self.atr_period + 5, 50):]

        if len(recent) < self.lookback_bars + 5:
            return None

        close = recent["Close"]
        high = recent["High"]
        low = recent["Low"]
        open_ = recent["Open"]

        # ── Range calculation ──────────────────────────────────
        # Use lookback_bars prior to the current bar to define the range
        # This simulates the Asian session range on H1 data,
        # or a prior-period consolidation range on daily data
        range_bars = recent.iloc[-(self.lookback_bars + 1):-1]
        range_high = range_bars["High"].max()
        range_low = range_bars["Low"].min()
        range_size = range_high - range_low

        # ── Range size filters ─────────────────────────────────
        if range_size < self._min_range:
            log.debug(
                "signal_rejected_range_too_small",
                range_pips=round(range_size / self.pip_size, 1),
                min_pips=self.min_range_pips,
            )
            return None

        if range_size > self._max_range:
            log.debug(
                "signal_rejected_range_too_large",
                range_pips=round(range_size / self.pip_size, 1),
                max_pips=self.max_range_pips,
            )
            return None

        # ── ATR volatility filter ──────────────────────────────
        atr_series = atr(high, low, close, self.atr_period)
        current_atr = atr_series.iloc[-1]

        if pd.isna(current_atr) or current_atr < self.pip_size * 5:
            log.debug("signal_rejected_low_volatility", atr=current_atr)
            return None

        # ── Current bar values ─────────────────────────────────
        current_close = close.iloc[-1]
        current_bar_time = recent.index[-1]

        # ── Day of week filter (if datetime index) ─────────────
        if hasattr(current_bar_time, "weekday"):
            dow = current_bar_time.weekday()
            if dow == 4:  # Friday — avoid late-week entries
                log.debug("signal_rejected_friday")
                return None

        # ── Entry condition: breakout ──────────────────────────
        breakout_up = current_close > range_high
        breakout_down = current_close < range_low

        if not breakout_up and not breakout_down:
            return None

        entry_price = current_close

        if breakout_up:
            direction = "BUY"
            stop_loss = range_low - self._sl_buffer
            risk_distance = entry_price - stop_loss
            take_profit = entry_price + (risk_distance * self.rr_ratio)
            confidence = self._calculate_confidence(
                range_size, current_atr, direction="BUY"
            )
        else:
            direction = "SELL"
            stop_loss = range_high + self._sl_buffer
            risk_distance = stop_loss - entry_price
            take_profit = entry_price - (risk_distance * self.rr_ratio)
            confidence = self._calculate_confidence(
                range_size, current_atr, direction="SELL"
            )

        # ── Final validation ───────────────────────────────────
        if risk_distance <= 0:
            return None

        rr = (abs(take_profit - entry_price)) / risk_distance
        if rr < 1.0:
            return None

        try:
            signal = TradeSignal(
                strategy_id=self.METADATA.strategy_id,
                instrument=instrument,
                direction=direction,
                entry_price=round(entry_price, 5),
                stop_loss=round(stop_loss, 5),
                take_profit=round(take_profit, 5),
                confidence=confidence,
                timeframe=timeframe,
                timestamp=current_bar_time if isinstance(current_bar_time, datetime)
                          else datetime.utcnow(),
                metadata={
                    "range_high": round(range_high, 5),
                    "range_low": round(range_low, 5),
                    "range_pips": round(range_size / self.pip_size, 1),
                    "atr": round(current_atr, 5),
                    "rr_ratio": round(rr, 2),
                },
            )
        except ValueError as e:
            log.debug("signal_construction_failed", error=str(e))
            return None

        log.debug(
            "signal_generated",
            direction=direction,
            entry=round(entry_price, 5),
            sl=round(stop_loss, 5),
            tp=round(take_profit, 5),
            range_pips=round(range_size / self.pip_size, 1),
            confidence=round(confidence, 2),
        )

        return signal

    def _calculate_confidence(
        self,
        range_size: float,
        current_atr: float,
        direction: str,
    ) -> float:
        """
        Calculate a signal confidence score (0.0–1.0).

        Confidence is higher when:
        - The range is a moderate proportion of ATR (not too tight, not too wide)
        - The breakout is clear (not marginal)

        This is a heuristic, not a probability estimate.
        """
        if current_atr <= 0:
            return 0.5

        # Ideal range: 30–70% of ATR
        range_atr_ratio = range_size / current_atr
        if 0.3 <= range_atr_ratio <= 0.7:
            confidence = 0.75
        elif 0.2 <= range_atr_ratio <= 1.0:
            confidence = 0.60
        else:
            confidence = 0.45

        return round(min(max(confidence, 0.0), 1.0), 2)
