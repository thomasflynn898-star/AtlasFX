from __future__ import annotations
from datetime import datetime
from typing import Optional
from data.database import DailySnapshot, Trade, get_session
from logs.logger import get_logger
log = get_logger(__name__)

class TradeJournal:
    def record_execution(self, result, account_balance):
        if not result.success or result.order_result is None: return None
        signal = result.signal; order = result.order_result
        pip_size = 0.01 if ("JPY" in signal.instrument or "XAU" in signal.instrument) else 0.0001
        trade = Trade(
            id=order.trade_id or f"PAPER_{datetime.utcnow().strftime("%Y%m%d%H%M%S%f")}",
            broker_order_id=order.order_id, strategy_id=signal.strategy_id,
            instrument=signal.instrument, timeframe=signal.timeframe,
            direction=signal.direction, status="OPEN",
            entry_price=order.entry_price, stop_loss=signal.stop_loss,
            take_profit=signal.take_profit, lot_size=order.units,
            account_balance_at_open=account_balance, is_paper=result.is_paper,
            open_time=result.executed_at,
            spread_cost=result.live_spread_pips * pip_size * order.units,
        )
        try:
            with get_session() as session: session.merge(trade)
            log.info("journal_trade_recorded", trade_id=trade.id, instrument=signal.instrument)
            return trade.id
        except Exception as e:
            log.error("journal_record_failed", error=str(e)); return None

    def record_close(self, trade_id, exit_price, close_reason, account_balance_after):
        try:
            with get_session() as session:
                trade = session.query(Trade).filter_by(id=trade_id).first()
                if not trade: return False
                trade.exit_price = exit_price; trade.close_time = datetime.utcnow()
                trade.close_reason = close_reason; trade.status = "CLOSED"
                pnl_price = (exit_price - trade.entry_price) if trade.direction=="BUY" else (trade.entry_price - exit_price)
                pip_size = 0.01 if ("JPY" in trade.instrument or "XAU" in trade.instrument) else 0.0001
                trade.pnl = round(pnl_price / pip_size * pip_size * trade.lot_size, 2)
                risk_dist = abs(trade.entry_price - trade.stop_loss)
                trade.r_multiple = round(pnl_price / risk_dist, 2) if risk_dist > 0 else 0
            log.info("journal_trade_closed", trade_id=trade_id, pnl=trade.pnl)
            return True
        except Exception as e:
            log.error("journal_close_failed", trade_id=trade_id, error=str(e)); return False

    def get_open_trades(self, is_paper=True):
        try:
            with get_session() as session:
                return session.query(Trade).filter_by(status="OPEN", is_paper=is_paper).all()
        except Exception as e:
            log.error("journal_query_failed", error=str(e)); return []

    def get_daily_stats(self, date=None):
        if date is None: date = datetime.utcnow().strftime("%Y-%m-%d")
        try:
            with get_session() as session:
                trades = session.query(Trade).filter(
                    Trade.status=="CLOSED",
                    Trade.close_time >= datetime.strptime(date, "%Y-%m-%d")).all()
            if not trades: return {"date":date,"trades":0,"pnl":0.0,"win_rate":0.0}
            wins = [t for t in trades if (t.pnl or 0) > 0]
            return {"date":date,"trades":len(trades),"wins":len(wins),
                    "losses":len(trades)-len(wins),"pnl":round(sum(t.pnl or 0 for t in trades),2),
                    "win_rate":round(len(wins)/len(trades)*100,1)}
        except Exception as e:
            log.error("journal_stats_failed", error=str(e)); return {"date":date,"error":str(e)}

    def save_daily_snapshot(self, date, opening_balance, closing_balance):
        stats = self.get_daily_stats(date)
        daily_pnl = closing_balance - opening_balance
        daily_pnl_pct = (daily_pnl/opening_balance*100) if opening_balance > 0 else 0
        snapshot = DailySnapshot(date=date, opening_balance=round(opening_balance,2),
            closing_balance=round(closing_balance,2), daily_pnl=round(daily_pnl,2),
            daily_pnl_pct=round(daily_pnl_pct,4), trades_opened=stats.get("trades",0),
            trades_closed=stats.get("trades",0), winning_trades=stats.get("wins",0),
            losing_trades=stats.get("losses",0))
        try:
            with get_session() as session: session.merge(snapshot)
            log.info("daily_snapshot_saved", date=date, pnl=round(daily_pnl,2))
        except Exception as e: log.error("snapshot_save_failed", error=str(e))
