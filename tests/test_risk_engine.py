"""
tests/test_risk_engine.py
──────────────────────────
Unit tests for the risk management engine.

Tests cover:
    - Position size calculation
    - Daily drawdown halt
    - Weekly drawdown halt
    - Maximum concurrent exposure rejection
    - R:R ratio enforcement
    - Signal approval happy path
    - Hard limit enforcement regardless of configuration
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from risk.engine import (
    HARD_DAILY_DRAWDOWN_HALT_PCT,
    HARD_MAX_CONCURRENT_EXPOSURE_PCT,
    HARD_MAX_RISK_PER_TRADE_PCT,
    HARD_MIN_RR_RATIO,
    HARD_WEEKLY_DRAWDOWN_HALT_PCT,
    RiskEngine,
)
from strategies.base import TradeSignal


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def engine() -> RiskEngine:
    """Standard risk engine with £10,000 account balance."""
    return RiskEngine(account_balance=10_000.0, risk_per_trade_pct=0.5)


@pytest.fixture
def buy_signal() -> TradeSignal:
    """Valid BUY signal with 2:1 R:R."""
    return TradeSignal(
        strategy_id="TEST_STRATEGY_V1",
        instrument="EUR_USD",
        direction="BUY",
        entry_price=1.08500,
        stop_loss=1.08300,   # 20 pips SL
        take_profit=1.08900, # 40 pips TP — 2:1 RR
        confidence=0.75,
        timeframe="H1",
        timestamp=datetime.utcnow(),
    )


@pytest.fixture
def sell_signal() -> TradeSignal:
    """Valid SELL signal with 2:1 R:R."""
    return TradeSignal(
        strategy_id="TEST_STRATEGY_V1",
        instrument="EUR_USD",
        direction="SELL",
        entry_price=1.08500,
        stop_loss=1.08700,   # 20 pips SL
        take_profit=1.08100, # 40 pips TP — 2:1 RR
        confidence=0.70,
        timeframe="H1",
        timestamp=datetime.utcnow(),
    )


# ── TradeSignal Tests ─────────────────────────────────────────────────────────

class TestTradeSignal:
    def test_valid_buy_signal_created(self, buy_signal):
        assert buy_signal.direction == "BUY"
        assert buy_signal.risk_reward_ratio == 2.0

    def test_valid_sell_signal_created(self, sell_signal):
        assert sell_signal.direction == "SELL"
        assert sell_signal.risk_reward_ratio == 2.0

    def test_buy_signal_invalid_stop_above_entry(self):
        with pytest.raises(ValueError, match="stop_loss.*below entry_price"):
            TradeSignal(
                strategy_id="TEST",
                instrument="EUR_USD",
                direction="BUY",
                entry_price=1.0850,
                stop_loss=1.0870,  # Above entry — invalid for BUY
                take_profit=1.0900,
                confidence=0.5,
                timeframe="H1",
                timestamp=datetime.utcnow(),
            )

    def test_sell_signal_invalid_stop_below_entry(self):
        with pytest.raises(ValueError, match="stop_loss.*above entry_price"):
            TradeSignal(
                strategy_id="TEST",
                instrument="EUR_USD",
                direction="SELL",
                entry_price=1.0850,
                stop_loss=1.0830,  # Below entry — invalid for SELL
                take_profit=1.0800,
                confidence=0.5,
                timeframe="H1",
                timestamp=datetime.utcnow(),
            )

    def test_confidence_out_of_range_raises(self):
        with pytest.raises(ValueError, match="Confidence"):
            TradeSignal(
                strategy_id="TEST",
                instrument="EUR_USD",
                direction="BUY",
                entry_price=1.0850,
                stop_loss=1.0830,
                take_profit=1.0900,
                confidence=1.5,  # Invalid
                timeframe="H1",
                timestamp=datetime.utcnow(),
            )

    def test_risk_pips_calculated(self, buy_signal):
        # 20 pip SL
        assert abs(buy_signal.risk_pips - 0.002) < 0.00001

    def test_reward_pips_calculated(self, buy_signal):
        # 40 pip TP
        assert abs(buy_signal.reward_pips - 0.004) < 0.00001


# ── RiskEngine Initialisation ─────────────────────────────────────────────────

class TestRiskEngineInit:
    def test_initialises_with_valid_balance(self):
        eng = RiskEngine(account_balance=5000.0)
        assert eng.drawdown_state.current_equity == 5000.0

    def test_rejects_zero_balance(self):
        with pytest.raises(ValueError, match="positive"):
            RiskEngine(account_balance=0.0)

    def test_rejects_negative_balance(self):
        with pytest.raises(ValueError, match="positive"):
            RiskEngine(account_balance=-1000.0)

    def test_risk_pct_capped_at_hard_max(self):
        eng = RiskEngine(account_balance=10000.0, risk_per_trade_pct=5.0)
        assert eng._configured_risk_pct == HARD_MAX_RISK_PER_TRADE_PCT


# ── Signal Evaluation: Happy Path ─────────────────────────────────────────────

class TestSignalEvaluation:
    def test_valid_signal_approved(self, engine, buy_signal):
        result = engine.evaluate_signal(buy_signal)
        assert result.approved is True
        assert result.lot_size > 0
        assert result.risk_amount > 0

    def test_approved_signal_has_correct_risk_amount(self, engine, buy_signal):
        result = engine.evaluate_signal(buy_signal)
        # 0.5% of £10,000 = £50
        assert abs(result.risk_amount - 50.0) < 5.0  # Allow for pip value approx

    def test_sell_signal_approved(self, engine, sell_signal):
        result = engine.evaluate_signal(sell_signal)
        assert result.approved is True


# ── Signal Evaluation: Rejection Cases ───────────────────────────────────────

class TestSignalRejection:
    def test_poor_rr_ratio_rejected(self, engine):
        signal = TradeSignal(
            strategy_id="TEST",
            instrument="EUR_USD",
            direction="BUY",
            entry_price=1.0850,
            stop_loss=1.0820,   # 30 pip SL
            take_profit=1.0865, # 15 pip TP — 0.5:1 RR — below minimum
            confidence=0.6,
            timeframe="H1",
            timestamp=datetime.utcnow(),
        )
        result = engine.evaluate_signal(signal)
        assert result.approved is False
        assert "R:R" in result.reason or "ratio" in result.reason.lower()

    def test_high_spread_rejected(self, engine, buy_signal):
        result = engine.evaluate_signal(
            buy_signal,
            current_spread_pips=5.0,
            max_spread_pips=3.0,
        )
        assert result.approved is False
        assert "Spread" in result.reason or "spread" in result.reason.lower()

    def test_max_exposure_rejected(self, engine, buy_signal):
        # Already at near-maximum concurrent exposure
        result = engine.evaluate_signal(
            buy_signal,
            current_open_exposure_pct=1.9,  # Adding ~0.5% would exceed 2%
        )
        assert result.approved is False
        assert "exposure" in result.reason.lower()

    def test_trading_halted_rejects_all(self, engine, buy_signal):
        engine._trading_halted = True
        engine._halt_reason = "Daily drawdown limit reached"
        result = engine.evaluate_signal(buy_signal)
        assert result.approved is False
        assert "halted" in result.reason.lower()


# ── Drawdown Tracking ─────────────────────────────────────────────────────────

class TestDrawdownTracking:
    def test_daily_drawdown_halts_trading(self, engine):
        assert not engine.is_halted
        # Simulate losses: drop below daily limit (2%)
        engine.update_equity(9_799.0)  # 2.01% daily loss
        assert engine.is_halted

    def test_weekly_drawdown_halts_trading(self):
        eng = RiskEngine(
            account_balance=10_000.0,
            daily_start_balance=9_999.0,   # Near perfect daily
            weekly_start_balance=10_000.0,
        )
        # Drop equity 5.1% from weekly start
        eng.update_equity(9_490.0)
        assert eng.is_halted

    def test_peak_equity_updates_on_profit(self, engine):
        engine.update_equity(10_500.0)
        assert engine.drawdown_state.peak_equity == 10_500.0

    def test_resume_trading_clears_halt(self, engine):
        engine._trading_halted = True
        engine._halt_reason = "test"
        engine.resume_trading()
        assert not engine.is_halted
        assert engine.halt_reason is None

    def test_drawdown_pct_calculated_correctly(self, engine):
        engine.update_equity(9_000.0)
        dd = engine.drawdown_state
        assert abs(dd.daily_drawdown_pct - 10.0) < 0.01


# ── Position Size Calculation ─────────────────────────────────────────────────

class TestPositionSizing:
    def test_position_size_positive(self, engine):
        units, risk = engine.calculate_position_size(
            instrument="EUR_USD",
            entry_price=1.0850,
            stop_loss=1.0830,
        )
        assert units > 0
        assert risk > 0

    def test_zero_stop_distance_returns_zero(self, engine):
        units, risk = engine.calculate_position_size(
            instrument="EUR_USD",
            entry_price=1.0850,
            stop_loss=1.0850,  # Same as entry
        )
        assert units == 0
        assert risk == 0

    def test_larger_stop_gives_smaller_units(self, engine):
        units_tight, _ = engine.calculate_position_size(
            "EUR_USD", 1.0850, 1.0830  # 20 pip SL
        )
        units_wide, _ = engine.calculate_position_size(
            "EUR_USD", 1.0850, 1.0800  # 50 pip SL
        )
        assert units_tight > units_wide

    def test_status_summary_returns_dict(self, engine):
        summary = engine.get_status_summary()
        assert isinstance(summary, dict)
        assert "current_equity" in summary
        assert "daily_drawdown_pct" in summary
        assert "trading_halted" in summary
