"""
strategies/base.py
──────────────────
Base class for all AtlasFX trading strategies.

Every strategy in the platform must inherit from BaseStrategy and implement
the generate_signal() method. This ensures:
    - Consistent signal interface across all strategies
    - Enforced metadata registration
    - Standardised logging
    - No strategy can bypass the signal contract

Usage:
    class MyStrategy(BaseStrategy):
        STRATEGY_ID = "MY_STRATEGY_V1"
        ...
        def generate_signal(self, data, instrument, timeframe):
            ...
            return TradeSignal(...)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional

import pandas as pd

from logs.logger import get_logger

log = get_logger(__name__)


# ── Signal dataclass ──────────────────────────────────────────────────────────

@dataclass
class TradeSignal:
    """
    Standardised trade signal returned by every strategy.

    All fields are required. No partial signals are permitted.
    The execution engine will reject any signal missing required fields.

    Attributes:
        strategy_id: Unique strategy identifier e.g. 'ICT_SILVER_BULLET_V1'
        instrument: OANDA-style pair e.g. 'EUR_USD'
        direction: 'BUY' or 'SELL'
        entry_price: Intended entry price
        stop_loss: Stop loss price
        take_profit: Take profit price
        confidence: Float 0.0–1.0. Strategy's self-assessed confidence.
                    This is NOT a probability of winning. It is a signal
                    quality score used for filtering, not for sizing.
        timeframe: Signal timeframe e.g. 'H1'
        timestamp: UTC datetime when signal was generated
        metadata: Dict of strategy-specific extras (e.g. ATR, pattern name)
    """
    strategy_id: str
    instrument: str
    direction: Literal["BUY", "SELL"]
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float
    timeframe: str
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate signal consistency after initialisation."""
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError(
                f"Confidence must be 0.0–1.0, got {self.confidence}"
            )
        if self.direction == "BUY":
            if self.stop_loss >= self.entry_price:
                raise ValueError(
                    f"BUY signal: stop_loss ({self.stop_loss}) must be "
                    f"below entry_price ({self.entry_price})"
                )
            if self.take_profit <= self.entry_price:
                raise ValueError(
                    f"BUY signal: take_profit ({self.take_profit}) must be "
                    f"above entry_price ({self.entry_price})"
                )
        elif self.direction == "SELL":
            if self.stop_loss <= self.entry_price:
                raise ValueError(
                    f"SELL signal: stop_loss ({self.stop_loss}) must be "
                    f"above entry_price ({self.entry_price})"
                )
            if self.take_profit >= self.entry_price:
                raise ValueError(
                    f"SELL signal: take_profit ({self.take_profit}) must be "
                    f"below entry_price ({self.entry_price})"
                )

    @property
    def risk_pips(self) -> float:
        """Distance from entry to stop loss in price units."""
        return abs(self.entry_price - self.stop_loss)

    @property
    def reward_pips(self) -> float:
        """Distance from entry to take profit in price units."""
        return abs(self.take_profit - self.entry_price)

    @property
    def risk_reward_ratio(self) -> float:
        """Risk:Reward ratio. Returns 0 if risk is zero."""
        if self.risk_pips == 0:
            return 0.0
        return round(self.reward_pips / self.risk_pips, 2)

    def __repr__(self) -> str:
        return (
            f"<TradeSignal {self.strategy_id} {self.instrument} "
            f"{self.direction} entry={self.entry_price:.5f} "
            f"SL={self.stop_loss:.5f} TP={self.take_profit:.5f} "
            f"RR={self.risk_reward_ratio} conf={self.confidence:.2f}>"
        )


# ── Strategy metadata ─────────────────────────────────────────────────────────

@dataclass
class StrategyMetadata:
    """
    Metadata that every strategy must declare.

    Used to populate the strategy_registry database table and
    to validate that a strategy has been properly documented.
    """
    strategy_id: str
    name: str
    version: str
    description: str
    instruments: list[str]
    timeframes: list[str]
    min_history_bars: int       # Minimum bars required before signals are valid


# ── Base strategy class ───────────────────────────────────────────────────────

class BaseStrategy(ABC):
    """
    Abstract base class for all AtlasFX trading strategies.

    Every strategy must:
        1. Define METADATA as a class-level StrategyMetadata instance
        2. Implement generate_signal()
        3. Never access external data sources directly — use the DataFrame passed in
        4. Be completely deterministic (same input always produces same output)
        5. Never raise exceptions from generate_signal() — return None instead

    The strategy is responsible for:
        - Detecting entry conditions
        - Setting stop loss
        - Setting take profit
        - Assigning a confidence score

    The strategy is NOT responsible for:
        - Position sizing (handled by risk engine)
        - Order submission (handled by execution engine)
        - Risk limit checks (handled by risk engine)
    """

    # Every concrete strategy must declare this
    METADATA: StrategyMetadata

    def __init__(self) -> None:
        if not hasattr(self, "METADATA"):
            raise NotImplementedError(
                f"{self.__class__.__name__} must define a METADATA class attribute"
            )
        self._log = get_logger(f"strategy.{self.METADATA.strategy_id}")


    @property
    def strategy_id(self) -> str:
        return self.METADATA.strategy_id

    @abstractmethod
    def generate_signal(
        self,
        data: pd.DataFrame,
        instrument: str,
        timeframe: str,
        current_bar_index: int = -1,
    ) -> Optional[TradeSignal]:
        """
        Analyse market data and return a trade signal if conditions are met.

        This method must be deterministic and must never raise exceptions.
        If conditions are not met, return None.

        Args:
            data: OHLCV DataFrame with columns Open, High, Low, Close, Volume.
                  Index is UTC datetime. All historical data up to and including
                  the current bar is provided. Do NOT look forward.
            instrument: The instrument being evaluated e.g. 'EUR_USD'
            timeframe: The timeframe of the data e.g. 'H1'
            current_bar_index: Index of the current bar (default -1 = last bar).
                               In backtesting this will be set to avoid look-ahead.

        Returns:
            TradeSignal if entry conditions are met, None otherwise.
        """
        ...

    def validate_data(self, data: pd.DataFrame, min_bars: int | None = None) -> bool:
        """
        Validate that the DataFrame has sufficient history and required columns.

        Args:
            data: Input OHLCV DataFrame
            min_bars: Minimum required bars. Defaults to METADATA.min_history_bars.

        Returns:
            True if data is valid, False otherwise.
        """
        required_cols = {"Open", "High", "Low", "Close"}
        if not required_cols.issubset(data.columns):
            missing = required_cols - set(data.columns)
            self._log.warning("invalid_data_missing_columns", missing=list(missing))
            return False

        min_b = min_bars or self.METADATA.min_history_bars
        if len(data) < min_b:
            self._log.debug(
                "insufficient_data",
                available=len(data),
                required=min_b,
                instrument=data.index.name or "unknown",
            )
            return False

        return True

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"id={self.METADATA.strategy_id} "
            f"v={self.METADATA.version}>"
        )
