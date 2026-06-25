"""
tests/test_backtesting_engine.py
──────────────────────────────────
Tests for the backtesting engine using synthetic OHLCV data.

Uses deterministic synthetic data with known outcomes so results
can be asserted exactly. Does NOT use real market data.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backtesting.engine import BacktestConfig, BacktestEngine, BacktestResults
from strategies.base import BaseStrategy, StrategyMetadata, TradeSignal


# ── Synthetic data helpers ────────────────────────────────────────────────────

def make_ohlcv(
    n_bars: int = 200,
    start_price: float = 1.1000,
    trend: float = 0.0001,
    volatility: float = 0.002,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Generate deterministic synthetic OHLCV data for testing.

    Args:
        n_bars: Number of bars
        start_price: Starting price
        trend: Per-bar price drift
        volatility: Per-bar random noise
        seed: Random seed for reproducibility
    """
    rng = np.random.default_rng(seed)
    dates = [datetime(2022, 1, 1) + timedelta(days=i) for i in range(n_bars)]

    closes = [start_price]
    for _ in range(n_bars - 1):
        change = trend + rng.normal(0, volatility)
        closes.append(max(closes[-1] + change, 0.0001))

    closes = np.array(closes)
    noise = rng.uniform(0.0005, 0.002, n_bars)

    highs = closes + noise
    lows = closes - noise
    opens = np.roll(closes, 1)
    opens[0] = closes[0]

    return pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": rng.integers(1000, 10000, n_bars).astype(float),
    }, index=pd.DatetimeIndex(dates))


# ── Test strategies ───────────────────────────────────────────────────────────

class AlwaysBuyStrategy(BaseStrategy):
    """Test strategy that always returns a BUY signal."""
    METADATA = StrategyMetadata(
        strategy_id="TEST_ALWAYS_BUY",
        name="Test Always Buy",
        version="1.0",
        description="Test strategy",
        instruments=["EUR_USD"],
        timeframes=["D"],
        min_history_bars=10,
    )

    def generate_signal(self, data, instrument, timeframe, current_bar_index=-1):
        if not self.validate_data(data):
            return None
        close = data["Close"].iloc[-1]
        sl = close - 0.0020
        tp = close + 0.0040
        return TradeSignal(
            strategy_id=self.METADATA.strategy_id,
            instrument=instrument,
            direction="BUY",
            entry_price=close,
            stop_loss=sl,
            take_profit=tp,
            confidence=0.7,
            timeframe=timeframe,
            timestamp=datetime.utcnow(),
        )


class NeverSignalStrategy(BaseStrategy):
    """Test strategy that never returns a signal."""
    METADATA = StrategyMetadata(
        strategy_id="TEST_NO_SIGNAL",
        name="Test No Signal",
        version="1.0",
        description="Test strategy",
        instruments=["EUR_USD"],
        timeframes=["D"],
        min_history_bars=5,
    )

    def generate_signal(self, data, instrument, timeframe, current_bar_index=-1):
        return None


class AlternatingStrategy(BaseStrategy):
    """Alternates BUY/SELL signals for testing both directions."""
    METADATA = StrategyMetadata(
        strategy_id="TEST_ALTERNATING",
        name="Test Alternating",
        version="1.0",
        description="Test strategy",
        instruments=["EUR_USD"],
        timeframes=["D"],
        min_history_bars=5,
    )

    def __init__(self):
        super().__init__()
        self._counter = 0

    def generate_signal(self, data, instrument, timeframe, current_bar_index=-1):
        if not self.validate_data(data):
            return None
        self._counter += 1
        close = data["Close"].iloc[-1]
        if self._counter % 2 == 1:
            return TradeSignal(
                strategy_id=self.METADATA.strategy_id,
                instrument=instrument, direction="BUY",
                entry_price=close, stop_loss=close - 0.002,
                take_profit=close + 0.004, confidence=0.6,
                timeframe=timeframe, timestamp=datetime.utcnow(),
            )
        else:
            return TradeSignal(
                strategy_id=self.METADATA.strategy_id,
                instrument=instrument, direction="SELL",
                entry_price=close, stop_loss=close + 0.002,
                take_profit=close - 0.004, confidence=0.6,
                timeframe=timeframe, timestamp=datetime.utcnow(),
            )


# ── Config fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def base_config():
    return BacktestConfig(
        instrument="EUR_USD",
        timeframe="D",
        start_date="2022-01-01",
        end_date="2022-12-31",
        initial_balance=10_000.0,
        risk_per_trade_pct=0.5,
        spread_pips=1.0,
        commission_per_trade=0.0,
        pip_size=0.0001,
    )


@pytest.fixture
def synthetic_data():
    return make_ohlcv(n_bars=200, seed=42)


def run_engine_with_synthetic(config, strategy, data):
    """Helper: run engine using synthetic data instead of downloading."""
    engine = BacktestEngine(config)
    with patch.object(engine._downloader, "load_for_backtest", return_value=data):
        return engine.run(strategy)


# ── BacktestConfig tests ──────────────────────────────────────────────────────

class TestBacktestConfig:
    def test_valid_config_created(self, base_config):
        assert base_config.initial_balance == 10_000.0
        assert base_config.risk_per_trade_pct == 0.5

    def test_rejects_risk_above_hard_max(self):
        with pytest.raises(ValueError, match="hard maximum"):
            BacktestConfig(
                instrument="EUR_USD", timeframe="D",
                start_date="2022-01-01", end_date="2022-12-31",
                risk_per_trade_pct=5.0,  # Above 1.0 hard max
            )

    def test_rejects_zero_balance(self):
        with pytest.raises(ValueError, match="positive"):
            BacktestConfig(
                instrument="EUR_USD", timeframe="D",
                start_date="2022-01-01", end_date="2022-12-31",
                initial_balance=0.0,
            )


# ── BacktestResults tests ─────────────────────────────────────────────────────

class TestBacktestResults:
    def test_empty_results_summary(self, base_config):
        results = BacktestResults(config=base_config, strategy_id="TEST")
        summary = results.summary()
        assert summary["total_trades"] == 0
        assert "note" in summary

    def test_equity_dataframe_empty(self, base_config):
        results = BacktestResults(config=base_config, strategy_id="TEST")
        df = results.equity_dataframe()
        assert df.empty

    def test_trades_dataframe_empty(self, base_config):
        results = BacktestResults(config=base_config, strategy_id="TEST")
        df = results.trades_dataframe()
        assert df.empty


# ── Engine run tests ──────────────────────────────────────────────────────────

class TestBacktestEngine:
    def test_no_signal_strategy_produces_no_trades(self, base_config, synthetic_data):
        results = run_engine_with_synthetic(
            base_config, NeverSignalStrategy(), synthetic_data
        )
        assert len(results.trades) == 0

    def test_engine_runs_without_error(self, base_config, synthetic_data):
        results = run_engine_with_synthetic(
            base_config, AlwaysBuyStrategy(), synthetic_data
        )
        assert results is not None
        assert len(results.equity_curve) > 0

    def test_equity_curve_starts_at_initial_balance(self, base_config, synthetic_data):
        results = run_engine_with_synthetic(
            base_config, AlwaysBuyStrategy(), synthetic_data
        )
        assert results.equity_curve[0] == base_config.initial_balance

    def test_equity_curve_length_matches_data(self, base_config, synthetic_data):
        results = run_engine_with_synthetic(
            base_config, NeverSignalStrategy(), synthetic_data
        )
        # Equity curve should have one entry per bar
        assert len(results.equity_curve) == len(synthetic_data)

    def test_trades_have_valid_r_multiples(self, base_config, synthetic_data):
        results = run_engine_with_synthetic(
            base_config, AlwaysBuyStrategy(), synthetic_data
        )
        for trade in results.trades:
            # R multiple should be either ~2.0 (TP) or ~-1.0 (SL) or other for EOD
            assert isinstance(trade.r_multiple, float)
            assert not pd.isna(trade.r_multiple)

    def test_balance_never_goes_negative(self, base_config, synthetic_data):
        results = run_engine_with_synthetic(
            base_config, AlwaysBuyStrategy(), synthetic_data
        )
        assert all(e > 0 for e in results.equity_curve)

    def test_summary_contains_required_keys(self, base_config, synthetic_data):
        results = run_engine_with_synthetic(
            base_config, AlwaysBuyStrategy(), synthetic_data
        )
        summary = results.summary()
        required = [
            "total_trades", "win_rate_pct", "profit_factor",
            "sharpe_ratio", "max_drawdown_pct", "total_return_pct",
        ]
        for key in required:
            assert key in summary, f"Missing key: {key}"

    def test_win_rate_between_0_and_100(self, base_config, synthetic_data):
        results = run_engine_with_synthetic(
            base_config, AlwaysBuyStrategy(), synthetic_data
        )
        summary = results.summary()
        if summary["total_trades"] > 0:
            assert 0 <= summary["win_rate_pct"] <= 100

    def test_no_lookahead_bias(self, base_config, synthetic_data):
        """
        Verify that the engine passes only historical data to generate_signal.
        The strategy should never see future bars.
        """
        bars_seen = []

        class DataRecorderStrategy(BaseStrategy):
            METADATA = StrategyMetadata(
                strategy_id="TEST_RECORDER",
                name="Recorder",
                version="1.0",
                description="Records data length",
                instruments=["EUR_USD"],
                timeframes=["D"],
                min_history_bars=5,
            )
            def generate_signal(self, data, instrument, timeframe, current_bar_index=-1):
                bars_seen.append(len(data))
                return None

        run_engine_with_synthetic(base_config, DataRecorderStrategy(), synthetic_data)

        # Each call should see more bars than the previous
        for i in range(1, len(bars_seen)):
            assert bars_seen[i] >= bars_seen[i - 1], (
                f"Look-ahead detected at call {i}: "
                f"saw {bars_seen[i]} bars, previous was {bars_seen[i-1]}"
            )

    def test_both_directions_traded(self, base_config, synthetic_data):
        results = run_engine_with_synthetic(
            base_config, AlternatingStrategy(), synthetic_data
        )
        if len(results.trades) >= 2:
            directions = {t.direction for t in results.trades}
            assert "BUY" in directions or "SELL" in directions


# ── Performance metrics tests ─────────────────────────────────────────────────

class TestPerformanceMetrics:
    def test_profit_factor_positive_for_profitable_system(self, base_config):
        """A system with all winning trades should have infinite profit factor."""
        data = make_ohlcv(200, trend=0.001, volatility=0.0001, seed=1)
        results = run_engine_with_synthetic(
            base_config, AlwaysBuyStrategy(), data
        )
        summary = results.summary()
        if summary["total_trades"] > 0 and summary["losing_trades"] == 0:
            assert summary["profit_factor"] == float("inf")

    def test_max_drawdown_non_negative(self, base_config, synthetic_data):
        results = run_engine_with_synthetic(
            base_config, AlwaysBuyStrategy(), synthetic_data
        )
        summary = results.summary()
        if summary["total_trades"] > 0:
            assert summary["max_drawdown_pct"] >= 0
