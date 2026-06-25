"""
risk/engine.py
──────────────
AtlasFX Risk Management Engine.

This module enforces all hard-coded risk rules. It is the gatekeeper
between signal generation and order execution.

Hard rules (cannot be overridden by config):
    - Risk per trade: capped at 1.0% regardless of config
    - Daily drawdown halt: 2.0% — ALL trading paused
    - Weekly drawdown halt: 5.0% — ALL trading paused
    - Maximum concurrent exposure: 2.0% of equity
    - No martingale / no averaging down (structural, not checked here)

The risk engine does NOT:
    - Generate signals
    - Submit orders
    - Know anything about broker APIs

Usage:
    from risk.engine import RiskEngine
    engine = RiskEngine(account_balance=10000.0)
    result = engine.evaluate_signal(signal, open_trades)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from logs.logger import get_logger, log_risk_event
from strategies.base import TradeSignal

log = get_logger(__name__)

# ── Hard-coded risk constants — NEVER modify without full system review ────────
HARD_MAX_RISK_PER_TRADE_PCT = 1.0       # Absolute ceiling
HARD_DAILY_DRAWDOWN_HALT_PCT = 2.0      # Halt all trading if hit
HARD_WEEKLY_DRAWDOWN_HALT_PCT = 5.0     # Halt all trading if hit
HARD_MAX_CONCURRENT_EXPOSURE_PCT = 2.0  # Total exposure across all open trades
HARD_MIN_RR_RATIO = 1.2                 # Reject any signal with R:R < 1.2


@dataclass
class RiskCheckResult:
    """Result of a risk evaluation."""
    approved: bool
    reason: str
    risk_amount: float = 0.0
    lot_size: float = 0.0
    adjusted_risk_pct: float = 0.0


@dataclass
class DrawdownState:
    """Current drawdown state tracking."""
    peak_equity: float
    current_equity: float
    daily_start_equity: float
    weekly_start_equity: float
    daily_start_date: str
    weekly_start_date: str

    @property
    def daily_drawdown_pct(self) -> float:
        if self.daily_start_equity <= 0:
            return 0.0
        return ((self.daily_start_equity - self.current_equity) / self.daily_start_equity) * 100

    @property
    def weekly_drawdown_pct(self) -> float:
        if self.weekly_start_equity <= 0:
            return 0.0
        return ((self.weekly_start_equity - self.current_equity) / self.weekly_start_equity) * 100

    @property
    def total_drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return ((self.peak_equity - self.current_equity) / self.peak_equity) * 100


class RiskEngine:
    """
    Evaluates trade signals against hard risk rules and calculates position size.

    This class is stateful — it tracks drawdown across the trading session.
    A new instance should be created per session, or state should be loaded
    from the database on restart.

    NOTE: Position size calculation uses a simplified model based on
    risk percentage and stop distance. It does not account for:
        - Currency conversion for non-USD pairs (approximated)
        - Exact broker lot constraints (rounded to 2 decimal places)
    These are refined in the execution engine which has access to broker data.
    """

    def __init__(
        self,
        account_balance: float,
        risk_per_trade_pct: float = 0.5,
        daily_start_balance: Optional[float] = None,
        weekly_start_balance: Optional[float] = None,
    ) -> None:
        """
        Initialise the risk engine.

        Args:
            account_balance: Current account balance in account currency
            risk_per_trade_pct: Default risk per trade (capped at HARD_MAX_RISK_PER_TRADE_PCT)
            daily_start_balance: Balance at the start of today (defaults to account_balance)
            weekly_start_balance: Balance at the start of this week (defaults to account_balance)
        """
        if account_balance <= 0:
            raise ValueError(f"Account balance must be positive, got {account_balance}")

        # Enforce hard ceiling on configured risk
        self._configured_risk_pct = min(risk_per_trade_pct, HARD_MAX_RISK_PER_TRADE_PCT)
        if risk_per_trade_pct > HARD_MAX_RISK_PER_TRADE_PCT:
            log.warning(
                "risk_pct_capped",
                requested=risk_per_trade_pct,
                capped_to=HARD_MAX_RISK_PER_TRADE_PCT,
            )

        today = datetime.utcnow().strftime("%Y-%m-%d")
        week_start = (datetime.utcnow() - timedelta(days=datetime.utcnow().weekday())).strftime("%Y-%m-%d")

        self._drawdown_state = DrawdownState(
            peak_equity=account_balance,
            current_equity=account_balance,
            daily_start_equity=daily_start_balance or account_balance,
            weekly_start_equity=weekly_start_balance or account_balance,
            daily_start_date=today,
            weekly_start_date=week_start,
        )

        self._trading_halted = False
        self._halt_reason: Optional[str] = None

        log.info(
            "risk_engine_initialised",
            balance=account_balance,
            risk_pct=self._configured_risk_pct,
            daily_dd_limit=HARD_DAILY_DRAWDOWN_HALT_PCT,
            weekly_dd_limit=HARD_WEEKLY_DRAWDOWN_HALT_PCT,
        )

    def update_equity(self, new_equity: float) -> None:
        """
        Update current equity and check drawdown limits.

        Call this after every trade close or at periodic intervals.
        """
        if new_equity <= 0:
            log.error("equity_update_invalid", value=new_equity)
            return

        self._drawdown_state.current_equity = new_equity

        # Update peak equity
        if new_equity > self._drawdown_state.peak_equity:
            self._drawdown_state.peak_equity = new_equity

        # Reset daily tracking if new day
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if today != self._drawdown_state.daily_start_date:
            self._drawdown_state.daily_start_equity = new_equity
            self._drawdown_state.daily_start_date = today
            log.info("daily_equity_reset", new_balance=new_equity, date=today)

        # Check drawdown limits
        self._check_drawdown_limits()

    def _check_drawdown_limits(self) -> None:
        """Check if any drawdown limit has been breached and halt if so."""
        dd = self._drawdown_state

        if dd.daily_drawdown_pct >= HARD_DAILY_DRAWDOWN_HALT_PCT:
            reason = (
                f"Daily drawdown {dd.daily_drawdown_pct:.2f}% "
                f"reached limit {HARD_DAILY_DRAWDOWN_HALT_PCT}%"
            )
            self._halt_trading(reason, event_type="daily_limit_hit")

        elif dd.weekly_drawdown_pct >= HARD_WEEKLY_DRAWDOWN_HALT_PCT:
            reason = (
                f"Weekly drawdown {dd.weekly_drawdown_pct:.2f}% "
                f"reached limit {HARD_WEEKLY_DRAWDOWN_HALT_PCT}%"
            )
            self._halt_trading(reason, event_type="weekly_limit_hit")

    def _halt_trading(self, reason: str, event_type: str) -> None:
        """Halt all trading and record the event."""
        if not self._trading_halted:
            self._trading_halted = True
            self._halt_reason = reason
            log_risk_event(
                log,
                event_type=event_type,
                current_value=self._drawdown_state.daily_drawdown_pct,
                limit_value=HARD_DAILY_DRAWDOWN_HALT_PCT,
                action_taken="trading_halted",
            )
            log.warning("trading_halted", reason=reason)

    def resume_trading(self) -> None:
        """
        Manually resume trading after a halt.

        This should only be called at the start of a new trading day/week
        after the drawdown period has reset.
        """
        if self._trading_halted:
            log.info("trading_resumed", previous_halt_reason=self._halt_reason)
            self._trading_halted = False
            self._halt_reason = None

    def calculate_position_size(
        self,
        instrument: str,
        entry_price: float,
        stop_loss: float,
        account_equity: Optional[float] = None,
        risk_pct_override: Optional[float] = None,
    ) -> tuple[float, float]:
        """
        Calculate the position size in units for a given trade.

        Uses the formula:
            risk_amount = equity * risk_pct
            pip_value = (pip_size / entry_price) * units  [for non-JPY]
            units = risk_amount / (stop_pips * pip_value_per_unit)

        NOTE: This is an approximation. For non-USD account currencies or
        non-USD quote currencies, the pip value calculation will be imprecise.
        The execution engine should recalculate using broker API data.

        Args:
            instrument: e.g. 'EUR_USD'
            entry_price: Intended entry price
            stop_loss: Stop loss price
            account_equity: Current equity (uses tracked equity if None)
            risk_pct_override: Override risk % for this trade (capped at hard max)

        Returns:
            Tuple of (units: float, risk_amount: float)
        """
        equity = account_equity or self._drawdown_state.current_equity

        # Determine risk percentage
        if risk_pct_override is not None:
            risk_pct = min(risk_pct_override, HARD_MAX_RISK_PER_TRADE_PCT) / 100
        else:
            risk_pct = self._configured_risk_pct / 100

        risk_amount = equity * risk_pct
        stop_distance = abs(entry_price - stop_loss)

        if stop_distance <= 0:
            log.error(
                "position_size_calc_failed",
                reason="zero_stop_distance",
                entry=entry_price,
                sl=stop_loss,
            )
            return 0.0, 0.0

        # Simplified pip value calculation (USD account, USD quote)
        # For production: use broker API to get precise pip values
        if "JPY" in instrument:
            pip_size = 0.01
        else:
            pip_size = 0.0001

        stop_pips = stop_distance / pip_size

        # Correct pip value calculation per unit
        # For JPY pairs: pip_value = pip_size / entry_price (convert to base currency)
        # For XAU/XAG: pip_value = pip_size (already in USD)
        # For standard pairs: pip_value = pip_size / entry_price * entry_price = pip_size
        if "JPY" in instrument:
            # JPY pairs: pip value = 0.01 / entry_price per unit
            pip_value_per_unit = pip_size / entry_price
        elif "XAU" in instrument:
            # Gold: 1 unit = 1 troy oz, pip = $0.01, value = $0.01 per unit
            # Stop distance in dollars not pips — use dollar risk directly
            pip_value_per_unit = 1.0  # 1 unit = $1 move per $1
            stop_pips = stop_distance  # Use raw price distance for gold
        elif "XAG" in instrument:
            # Silver: similar to gold
            pip_value_per_unit = 1.0
            stop_pips = stop_distance
        else:
            # Standard pairs: pip value per unit in quote currency
            pip_value_per_unit = pip_size

        units = risk_amount / (stop_pips * pip_value_per_unit)

        # Unit caps scale with account size (no arbitrary ceiling)
        if "XAU" in instrument:
            units = min(units, 500)   # Max 500 oz gold
        elif "XAG" in instrument:
            units = min(units, 50000) # Max 50000 oz silver
        # No cap on FX pairs — let risk engine determine size naturally

        # Round to nearest whole unit
        units = round(units)

        log.debug(
            "position_size_calculated",
            instrument=instrument,
            equity=round(equity, 2),
            risk_pct=round(risk_pct * 100, 2),
            risk_amount=round(risk_amount, 2),
            stop_pips=round(stop_pips, 1),
            units=units,
        )

        return units, risk_amount

    def evaluate_signal(
        self,
        signal: TradeSignal,
        current_open_exposure_pct: float = 0.0,
        current_spread_pips: float = 0.0,
        max_spread_pips: float = 3.0,
    ) -> RiskCheckResult:
        """
        Evaluate a trade signal against all risk rules.

        This is the primary gatekeeper. Returns approved=False with a reason
        if any rule is violated.

        Args:
            signal: The trade signal to evaluate
            current_open_exposure_pct: Current total exposure as % of equity
            current_spread_pips: Current live spread in pips
            max_spread_pips: Maximum acceptable spread (strategy-configurable)

        Returns:
            RiskCheckResult with approved status and reason
        """
        # ── Hard check 1: Trading halted ──────────────────────
        if self._trading_halted:
            return RiskCheckResult(
                approved=False,
                reason=f"Trading halted: {self._halt_reason}",
            )

        # ── Hard check 2: R:R ratio ────────────────────────────
        if signal.risk_reward_ratio < HARD_MIN_RR_RATIO:
            return RiskCheckResult(
                approved=False,
                reason=(
                    f"R:R ratio {signal.risk_reward_ratio:.2f} "
                    f"below minimum {HARD_MIN_RR_RATIO}"
                ),
            )

        # ── Hard check 3: Spread filter ───────────────────────
        if current_spread_pips > max_spread_pips:
            return RiskCheckResult(
                approved=False,
                reason=(
                    f"Spread {current_spread_pips:.1f} pips "
                    f"exceeds max {max_spread_pips:.1f} pips"
                ),
            )

        # ── Hard check 4: Concurrent exposure ─────────────────
        units, risk_amount = self.calculate_position_size(
            instrument=signal.instrument,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
        )

        if units <= 0:
            return RiskCheckResult(
                approved=False,
                reason="Position size calculation returned zero — check stop distance",
            )

        equity = self._drawdown_state.current_equity
        new_trade_risk_pct = (risk_amount / equity) * 100
        total_exposure = current_open_exposure_pct + new_trade_risk_pct

        if total_exposure > HARD_MAX_CONCURRENT_EXPOSURE_PCT:
            log_risk_event(
                log,
                event_type="max_exposure",
                current_value=total_exposure,
                limit_value=HARD_MAX_CONCURRENT_EXPOSURE_PCT,
                action_taken="signal_rejected",
            )
            return RiskCheckResult(
                approved=False,
                reason=(
                    f"Adding this trade would bring total exposure to "
                    f"{total_exposure:.2f}%, exceeding the "
                    f"{HARD_MAX_CONCURRENT_EXPOSURE_PCT}% limit"
                ),
            )

        # ── All checks passed ─────────────────────────────────
        log.info(
            "signal_approved",
            strategy=signal.strategy_id,
            instrument=signal.instrument,
            direction=signal.direction,
            units=units,
            risk_amount=round(risk_amount, 2),
            risk_pct=round(new_trade_risk_pct, 2),
            rr=signal.risk_reward_ratio,
        )

        return RiskCheckResult(
            approved=True,
            reason="All risk checks passed",
            risk_amount=round(risk_amount, 2),
            lot_size=units,
            adjusted_risk_pct=round(new_trade_risk_pct, 2),
        )

    @property
    def drawdown_state(self) -> DrawdownState:
        return self._drawdown_state

    @property
    def is_halted(self) -> bool:
        return self._trading_halted

    @property
    def halt_reason(self) -> Optional[str]:
        return self._halt_reason

    def get_status_summary(self) -> dict:
        """Return a summary of current risk state for monitoring."""
        dd = self._drawdown_state
        return {
            "trading_halted": self._trading_halted,
            "halt_reason": self._halt_reason,
            "current_equity": round(dd.current_equity, 2),
            "peak_equity": round(dd.peak_equity, 2),
            "daily_drawdown_pct": round(dd.daily_drawdown_pct, 2),
            "weekly_drawdown_pct": round(dd.weekly_drawdown_pct, 2),
            "total_drawdown_pct": round(dd.total_drawdown_pct, 2),
            "daily_limit_pct": HARD_DAILY_DRAWDOWN_HALT_PCT,
            "weekly_limit_pct": HARD_WEEKLY_DRAWDOWN_HALT_PCT,
            "configured_risk_pct": self._configured_risk_pct,
        }
