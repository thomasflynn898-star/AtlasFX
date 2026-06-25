from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from broker.base import BaseBroker, OrderResult
from logs.logger import get_logger, log_trade_open
from risk.engine import RiskCheckResult, RiskEngine
from strategies.base import TradeSignal
log = get_logger(__name__)

@dataclass
class ExecutionConfig:
    max_spread_pips: float = 3.0
    max_slippage_pips: float = 2.0
    retry_on_failure: bool = True
    max_retries: int = 2
    retry_delay_seconds: float = 1.0
    is_paper_mode: bool = True
    min_account_balance: float = 100.0

@dataclass
class ExecutionResult:
    success: bool
    signal: TradeSignal
    order_result: Optional[OrderResult]
    rejection_reason: Optional[str]
    is_paper: bool
    executed_at: datetime
    live_spread_pips: float = 0.0
    live_bid: float = 0.0
    live_ask: float = 0.0

class ExecutionEngine:
    def __init__(self, broker: BaseBroker, risk_engine: RiskEngine, config: Optional[ExecutionConfig] = None):
        self._broker = broker
        self._risk_engine = risk_engine
        self._config = config or ExecutionConfig()
        if not self._config.is_paper_mode:
            log.warning("execution_engine_live_mode", message="LIVE MODE ENABLED")
        else:
            log.info("execution_engine_paper_mode")

    def execute(self, signal: TradeSignal, risk_result: RiskCheckResult) -> ExecutionResult:
        now = datetime.utcnow()
        if not risk_result.approved:
            return ExecutionResult(success=False,signal=signal,order_result=None,
                rejection_reason=f"Risk check failed: {risk_result.reason}",
                is_paper=self._config.is_paper_mode,executed_at=now)
        try:
            account = self._broker.get_account()
        except Exception as e:
            return ExecutionResult(success=False,signal=signal,order_result=None,
                rejection_reason=f"Could not fetch account info: {e}",
                is_paper=self._config.is_paper_mode,executed_at=now)
        if account.balance < self._config.min_account_balance:
            return ExecutionResult(success=False,signal=signal,order_result=None,
                rejection_reason=f"Account balance {account.balance:.2f} below minimum {self._config.min_account_balance:.2f}",
                is_paper=self._config.is_paper_mode,executed_at=now)
        try:
            live_price = self._broker.get_price(signal.instrument)
        except Exception as e:
            return ExecutionResult(success=False,signal=signal,order_result=None,
                rejection_reason=f"Could not fetch live price: {e}",
                is_paper=self._config.is_paper_mode,executed_at=now)
        pip_size = 0.01 if ("JPY" in signal.instrument or "XAU" in signal.instrument) else 0.0001
        live_spread_pips = live_price.spread / pip_size
        if live_spread_pips > self._config.max_spread_pips:
            log.warning("execution_rejected_spread",instrument=signal.instrument,
                spread_pips=round(live_spread_pips,1),max_pips=self._config.max_spread_pips)
            return ExecutionResult(success=False,signal=signal,order_result=None,
                rejection_reason=f"Live spread {live_spread_pips:.1f} pips exceeds maximum {self._config.max_spread_pips:.1f} pips",
                is_paper=self._config.is_paper_mode,executed_at=now,
                live_spread_pips=live_spread_pips,live_bid=live_price.bid,live_ask=live_price.ask)
        entry_price = live_price.ask if signal.direction=="BUY" else live_price.bid
        risk_override = getattr(risk_result, "risk_pct_override", None)
        # Use signal entry price for position sizing to preserve correct SL distance
        sizing_entry = signal.entry_price if signal.entry_price > 0 else entry_price
        units, risk_amount = self._risk_engine.calculate_position_size(
            instrument=signal.instrument,entry_price=sizing_entry,
            stop_loss=signal.stop_loss,account_equity=account.nav,
            risk_pct_override=risk_override)
        if units <= 0:
            return ExecutionResult(success=False,signal=signal,order_result=None,
                rejection_reason="Position size calculated as zero",
                is_paper=self._config.is_paper_mode,executed_at=now)
        if self._config.is_paper_mode:
            log.info("execution_paper_simulated",instrument=signal.instrument,
                direction=signal.direction,units=units,entry=entry_price)
            paper_result = OrderResult(success=True,
                order_id=f"PAPER_{now.strftime("%Y%m%d%H%M%S")}",
                trade_id=f"PAPER_{signal.instrument}_{now.strftime("%H%M%S")}",
                instrument=signal.instrument,direction=signal.direction,
                units=units,entry_price=entry_price,
                stop_loss=signal.stop_loss,take_profit=signal.take_profit)
            log_trade_open(log,instrument=signal.instrument,direction=signal.direction,
                entry_price=entry_price,stop_loss=signal.stop_loss,take_profit=signal.take_profit,
                lot_size=units,strategy_id=signal.strategy_id,order_id=paper_result.order_id,is_paper=True)
            return ExecutionResult(success=True,signal=signal,order_result=paper_result,
                rejection_reason=None,is_paper=True,executed_at=now,
                live_spread_pips=live_spread_pips,live_bid=live_price.bid,live_ask=live_price.ask)
        log.warning("execution_live_order_submitting",instrument=signal.instrument,
            direction=signal.direction,units=units,entry=entry_price)
        order_result = self._submit_with_retry(signal.instrument,signal.direction,units,
            signal.stop_loss,signal.take_profit)
        if order_result.success:
            log_trade_open(log,instrument=signal.instrument,direction=signal.direction,
                entry_price=order_result.entry_price,stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,lot_size=units,strategy_id=signal.strategy_id,
                order_id=order_result.order_id,is_paper=False)
            self._risk_engine.update_equity(account.nav)
        return ExecutionResult(success=order_result.success,signal=signal,order_result=order_result,
            rejection_reason=order_result.error_message if not order_result.success else None,
            is_paper=False,executed_at=now,live_spread_pips=live_spread_pips,
            live_bid=live_price.bid,live_ask=live_price.ask)

    def _submit_with_retry(self, instrument, direction, units, stop_loss, take_profit):
        import time
        last_error = None
        attempts = 1 + (self._config.max_retries if self._config.retry_on_failure else 0)
        for attempt in range(attempts):
            if attempt > 0: time.sleep(self._config.retry_delay_seconds)
            try:
                result = self._broker.submit_market_order(instrument,direction,units,stop_loss,take_profit)
                if result.success: return result
                last_error = result.error_message
            except Exception as e:
                last_error = str(e)
        from broker.base import OrderResult as OR
        return OR(success=False,order_id=None,trade_id=None,instrument=instrument,direction=direction,
            units=units,entry_price=0,stop_loss=stop_loss,take_profit=take_profit,
            error_message=f"All {attempts} attempts failed. Last: {last_error}")

    def close_position(self, trade_id): return self._broker.close_trade(trade_id)
    def get_open_positions(self): return self._broker.get_open_trades()
