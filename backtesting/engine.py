"""
backtesting/engine.py
──────────────────────
AtlasFX event-driven backtesting engine.

Design principles:
    - Strict bar-by-bar simulation — no look-ahead bias
    - Each bar: check exits first, then check entries
    - Spread and commission deducted on every trade
    - One trade per strategy per instrument at a time
    - All results are recorded, not summarised in memory

The engine does NOT:
    - Optimise parameters (that is parameter_search.py)
    - Run walk-forward (that is walk_forward.py)
    - Run Monte Carlo (that is monte_carlo.py)

Usage:
    from backtesting.engine import BacktestEngine, BacktestConfig
    from strategies.strategy_london_breakout import LondonBreakoutStrategy

    config = BacktestConfig(
        instrument="EUR_USD",
        timeframe="D",
        start_date="2022-01-01",
        end_date="2024-01-01",
        initial_balance=10000.0,
        risk_per_trade_pct=0.5,
        spread_pips=1.0,
        commission_per_trade=0.0,
    )
    engine = BacktestEngine(config)
    results = engine.run(LondonBreakoutStrategy())
    print(results.summary())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from data.downloader import HistoricalDownloader
from logs.logger import get_logger
from risk.engine import HARD_MAX_RISK_PER_TRADE_PCT, RiskEngine
from strategies.base import BaseStrategy, TradeSignal

log = get_logger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass
class BacktestConfig:
    """
    Configuration for a single backtest run.

    Attributes:
        instrument: e.g. 'EUR_USD'
        timeframe: e.g. 'D' or 'H1'
        start_date: Inclusive start date 'YYYY-MM-DD'
        end_date: Inclusive end date 'YYYY-MM-DD'
        initial_balance: Starting account balance
        risk_per_trade_pct: Risk per trade as % of equity (max 1.0)
        spread_pips: Assumed spread in pips (deducted on entry)
        commission_per_trade: Fixed commission per trade in account currency
        pip_size: Size of one pip (0.0001 for most pairs, 0.01 for JPY)
        max_open_trades: Maximum concurrent open trades (default 1)
        slippage_pips: Additional slippage on entry (default 0)
    """
    instrument: str
    timeframe: str
    start_date: str
    end_date: str
    initial_balance: float = 10_000.0
    risk_per_trade_pct: float = 0.5
    spread_pips: float = 1.0
    commission_per_trade: float = 0.0
    pip_size: float = 0.0001
    max_open_trades: int = 1
    slippage_pips: float = 0.0

    def __post_init__(self) -> None:
        if self.risk_per_trade_pct > HARD_MAX_RISK_PER_TRADE_PCT:
            raise ValueError(
                f"risk_per_trade_pct {self.risk_per_trade_pct} exceeds "
                f"hard maximum {HARD_MAX_RISK_PER_TRADE_PCT}"
            )
        if self.initial_balance <= 0:
            raise ValueError("initial_balance must be positive")


# ── Trade record ──────────────────────────────────────────────────────────────

@dataclass
class BacktestTrade:
    """A single completed trade record from the backtest."""
    trade_id: int
    strategy_id: str
    instrument: str
    direction: str
    entry_bar: int
    entry_time: datetime
    entry_price: float
    stop_loss: float
    take_profit: float
    exit_bar: int
    exit_time: datetime
    exit_price: float
    lot_size: float
    pnl: float
    r_multiple: float
    close_reason: str           # 'take_profit' | 'stop_loss' | 'end_of_data'
    spread_cost: float
    commission: float
    balance_before: float
    balance_after: float


# ── Results ───────────────────────────────────────────────────────────────────

@dataclass
class BacktestResults:
    """Complete results from a backtest run."""
    config: BacktestConfig
    strategy_id: str
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    equity_dates: list[datetime] = field(default_factory=list)
    signals_generated: int = 0
    signals_rejected: int = 0

    def summary(self) -> dict:
        """
        Calculate and return performance statistics.

        Returns a dict of metrics. All metrics are calculated from
        actual trade records — nothing is fabricated or assumed.
        """
        if not self.trades:
            return {
                "strategy_id": self.strategy_id,
                "instrument": self.config.instrument,
                "timeframe": self.config.timeframe,
                "period": f"{self.config.start_date} → {self.config.end_date}",
                "total_trades": 0,
                "note": "No trades generated in this period.",
            }

        pnls = [t.pnl for t in self.trades]
        r_multiples = [t.r_multiple for t in self.trades]
        wins = [t for t in self.trades if t.pnl > 0]
        losses = [t for t in self.trades if t.pnl <= 0]

        win_rate = len(wins) / len(self.trades) * 100

        gross_profit = sum(t.pnl for t in wins) if wins else 0
        gross_loss = abs(sum(t.pnl for t in losses)) if losses else 0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

        # Sharpe ratio (annualised, assuming daily returns)
        if len(self.equity_curve) > 1:
            equity_series = pd.Series(self.equity_curve)
            daily_returns = equity_series.pct_change().dropna()
            sharpe = (
                (daily_returns.mean() / daily_returns.std() * np.sqrt(252))
                if daily_returns.std() > 0 else 0.0
            )
        else:
            sharpe = 0.0

        # Maximum drawdown
        equity_series = pd.Series(self.equity_curve)
        rolling_max = equity_series.cummax()
        drawdown = (equity_series - rolling_max) / rolling_max * 100
        max_drawdown_pct = abs(drawdown.min())

        # Consecutive losses
        max_consec_losses = 0
        current_consec = 0
        for t in self.trades:
            if t.pnl <= 0:
                current_consec += 1
                max_consec_losses = max(max_consec_losses, current_consec)
            else:
                current_consec = 0

        final_balance = self.equity_curve[-1] if self.equity_curve else self.config.initial_balance
        total_return_pct = (final_balance / self.config.initial_balance - 1) * 100

        return {
            "strategy_id": self.strategy_id,
            "instrument": self.config.instrument,
            "timeframe": self.config.timeframe,
            "period": f"{self.config.start_date} → {self.config.end_date}",
            "initial_balance": round(self.config.initial_balance, 2),
            "final_balance": round(final_balance, 2),
            "total_return_pct": round(total_return_pct, 2),
            "total_trades": len(self.trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate_pct": round(win_rate, 2),
            "profit_factor": round(profit_factor, 3),
            "sharpe_ratio": round(sharpe, 3),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "max_consecutive_losses": max_consec_losses,
            "avg_r_multiple": round(np.mean(r_multiples), 3),
            "avg_win": round(np.mean([t.pnl for t in wins]), 2) if wins else 0,
            "avg_loss": round(np.mean([t.pnl for t in losses]), 2) if losses else 0,
            "largest_win": round(max(pnls), 2),
            "largest_loss": round(min(pnls), 2),
            "signals_generated": self.signals_generated,
            "signals_rejected": self.signals_rejected,
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "total_commission": round(sum(t.commission for t in self.trades), 2),
            "total_spread_cost": round(sum(t.spread_cost for t in self.trades), 2),
        }

    def equity_dataframe(self) -> pd.DataFrame:
        """Return equity curve as a DataFrame for charting."""
        return pd.DataFrame({
            "date": self.equity_dates,
            "equity": self.equity_curve,
        }).set_index("date")

    def trades_dataframe(self) -> pd.DataFrame:
        """Return all trades as a DataFrame."""
        if not self.trades:
            return pd.DataFrame()
        return pd.DataFrame([t.__dict__ for t in self.trades])


# ── Engine ────────────────────────────────────────────────────────────────────

class BacktestEngine:
    """
    Event-driven bar-by-bar backtesting engine.

    Iteration logic per bar:
        1. Check if any open trade hits stop loss on this bar
        2. Check if any open trade hits take profit on this bar
        3. Ask strategy for a signal on the closed bar (no look-ahead)
        4. If signal returned and no open trade: evaluate risk, open trade

    Stop/TP check order: stop loss is checked before take profit.
    If both are hit on the same bar, stop loss is assumed (conservative).

    This engine has NOT been validated against a live broker.
    Results are simulated approximations, not guaranteed outcomes.
    """

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self._downloader = HistoricalDownloader()
        log.info(
            "backtest_engine_initialised",
            instrument=config.instrument,
            timeframe=config.timeframe,
            start=config.start_date,
            end=config.end_date,
            balance=config.initial_balance,
        )

    def run(self, strategy: BaseStrategy) -> BacktestResults:
        """
        Run a full backtest for the given strategy.

        Args:
            strategy: An instantiated BaseStrategy subclass

        Returns:
            BacktestResults with all trades and equity curve
        """
        log.info(
            "backtest_start",
            strategy=strategy.strategy_id,
            instrument=self.config.instrument,
        )

        # Load data
        data = self._downloader.load_for_backtest(
            instrument=self.config.instrument,
            timeframe=self.config.timeframe,
            start=self.config.start_date,
            end=self.config.end_date,
        )

        if data.empty:
            raise ValueError(
                f"No data for {self.config.instrument} "
                f"{self.config.timeframe} "
                f"{self.config.start_date}→{self.config.end_date}"
            )

        results = BacktestResults(
            config=self.config,
            strategy_id=strategy.strategy_id,
        )

        balance = self.config.initial_balance
        risk_engine = RiskEngine(
            account_balance=balance,
            risk_per_trade_pct=self.config.risk_per_trade_pct,
        )

        open_trade: Optional[dict] = None
        trade_id_counter = 0
        spread = self.config.spread_pips * self.config.pip_size
        slippage = self.config.slippage_pips * self.config.pip_size

        results.equity_curve.append(balance)
        results.equity_dates.append(data.index[0])

        # ── Bar loop ───────────────────────────────────────────
        for i in range(1, len(data)):
            bar = data.iloc[i]
            bar_time = data.index[i]
            bar_high = bar["High"]
            bar_low = bar["Low"]
            bar_close = bar["Close"]

            # ── Step 1: Check exits on open trade ──────────────
            if open_trade is not None:
                direction = open_trade["direction"]
                sl = open_trade["stop_loss"]
                tp = open_trade["take_profit"]
                entry = open_trade["entry_price"]
                lots = open_trade["lot_size"]

                exit_price = None
                close_reason = None

                if direction == "BUY":
                    # Stop loss hit first (conservative)
                    if bar_low <= sl:
                        exit_price = sl
                        close_reason = "stop_loss"
                    elif bar_high >= tp:
                        exit_price = tp
                        close_reason = "take_profit"
                elif direction == "SELL":
                    if bar_high >= sl:
                        exit_price = sl
                        close_reason = "stop_loss"
                    elif bar_low <= tp:
                        exit_price = tp
                        close_reason = "take_profit"

                if exit_price is not None:
                    # Calculate P&L
                    if direction == "BUY":
                        pnl_pips = (exit_price - entry) / self.config.pip_size
                    else:
                        pnl_pips = (entry - exit_price) / self.config.pip_size

                    risk_pips = abs(entry - sl) / self.config.pip_size
                    r_multiple = pnl_pips / risk_pips if risk_pips > 0 else 0

                    # Simplified P&L in account currency
                    pnl = pnl_pips * self.config.pip_size * lots
                    spread_cost = spread * lots
                    commission = self.config.commission_per_trade

                    net_pnl = pnl - spread_cost - commission
                    balance_before = balance
                    balance += net_pnl
                    balance = round(balance, 2)

                    risk_engine.update_equity(balance)

                    trade = BacktestTrade(
                        trade_id=open_trade["trade_id"],
                        strategy_id=strategy.strategy_id,
                        instrument=self.config.instrument,
                        direction=direction,
                        entry_bar=open_trade["entry_bar"],
                        entry_time=open_trade["entry_time"],
                        entry_price=entry,
                        stop_loss=sl,
                        take_profit=tp,
                        exit_bar=i,
                        exit_time=bar_time,
                        exit_price=exit_price,
                        lot_size=lots,
                        pnl=round(net_pnl, 4),
                        r_multiple=round(r_multiple, 2),
                        close_reason=close_reason,
                        spread_cost=round(spread_cost, 4),
                        commission=commission,
                        balance_before=round(balance_before, 2),
                        balance_after=round(balance, 2),
                    )
                    results.trades.append(trade)
                    open_trade = None

                    log.debug(
                        "backtest_trade_closed",
                        reason=close_reason,
                        pnl=round(net_pnl, 2),
                        r=round(r_multiple, 2),
                        balance=balance,
                    )

            results.equity_curve.append(balance)
            results.equity_dates.append(bar_time)

            # ── Step 2: Generate signal on completed bar ────────
            if open_trade is not None:
                continue  # Already have a trade open

            if risk_engine.is_halted:
                continue  # Risk limit breached

            signal = strategy.generate_signal(
                data=data.iloc[:i],        # Only past data — no look-ahead
                instrument=self.config.instrument,
                timeframe=self.config.timeframe,
                current_bar_index=-1,
            )

            results.signals_generated += 1 if signal else 0

            if signal is None:
                continue

            # ── Step 3: Risk check ──────────────────────────────
            risk_result = risk_engine.evaluate_signal(
                signal,
                current_spread_pips=self.config.spread_pips,
                max_spread_pips=self.config.spread_pips * 2,
            )

            if not risk_result.approved:
                results.signals_rejected += 1
                continue

            # ── Step 4: Open trade ──────────────────────────────
            # Entry on next bar open (realistic — we can't trade on the signal bar)
            if i + 1 >= len(data):
                continue

            next_bar = data.iloc[i + 1] if i + 1 < len(data) else None
            if next_bar is None:
                continue

            if signal.direction == "BUY":
                actual_entry = next_bar["Open"] + slippage
            else:
                actual_entry = next_bar["Open"] - slippage

            # Recalculate SL/TP relative to actual entry
            sl_distance = abs(signal.entry_price - signal.stop_loss)
            tp_distance = abs(signal.take_profit - signal.entry_price)

            if signal.direction == "BUY":
                actual_sl = actual_entry - sl_distance
                actual_tp = actual_entry + tp_distance
            else:
                actual_sl = actual_entry + sl_distance
                actual_tp = actual_entry - tp_distance

            # Recalculate lot size based on actual entry
            lots, risk_amt = risk_engine.calculate_position_size(
                instrument=self.config.instrument,
                entry_price=actual_entry,
                stop_loss=actual_sl,
                account_equity=balance,
            )

            if lots <= 0:
                continue

            trade_id_counter += 1
            open_trade = {
                "trade_id": trade_id_counter,
                "direction": signal.direction,
                "entry_price": actual_entry,
                "stop_loss": actual_sl,
                "take_profit": actual_tp,
                "lot_size": lots,
                "entry_bar": i + 1,
                "entry_time": data.index[i + 1] if i + 1 < len(data) else bar_time,
            }

            log.debug(
                "backtest_trade_opened",
                direction=signal.direction,
                entry=round(actual_entry, 5),
                sl=round(actual_sl, 5),
                tp=round(actual_tp, 5),
            )

        # ── Close any open trade at end of data ────────────────
        if open_trade is not None:
            last_bar = data.iloc[-1]
            exit_price = last_bar["Close"]
            direction = open_trade["direction"]
            entry = open_trade["entry_price"]
            sl = open_trade["stop_loss"]
            lots = open_trade["lot_size"]

            if direction == "BUY":
                pnl_pips = (exit_price - entry) / self.config.pip_size
            else:
                pnl_pips = (entry - exit_price) / self.config.pip_size

            risk_pips = abs(entry - sl) / self.config.pip_size
            r_multiple = pnl_pips / risk_pips if risk_pips > 0 else 0
            pnl = pnl_pips * self.config.pip_size * lots
            net_pnl = pnl - self.config.commission_per_trade
            balance += net_pnl

            results.trades.append(BacktestTrade(
                trade_id=open_trade["trade_id"],
                strategy_id=strategy.strategy_id,
                instrument=self.config.instrument,
                direction=direction,
                entry_bar=open_trade["entry_bar"],
                entry_time=open_trade["entry_time"],
                entry_price=entry,
                stop_loss=sl,
                take_profit=open_trade["take_profit"],
                exit_bar=len(data) - 1,
                exit_time=data.index[-1],
                exit_price=exit_price,
                lot_size=lots,
                pnl=round(net_pnl, 4),
                r_multiple=round(r_multiple, 2),
                close_reason="end_of_data",
                spread_cost=0.0,
                commission=self.config.commission_per_trade,
                balance_before=round(balance - net_pnl, 2),
                balance_after=round(balance, 2),
            ))
            results.equity_curve[-1] = round(balance, 2)

        log.info(
            "backtest_complete",
            strategy=strategy.strategy_id,
            trades=len(results.trades),
            final_balance=round(balance, 2),
            return_pct=round((balance / self.config.initial_balance - 1) * 100, 2),
        )

        return results
