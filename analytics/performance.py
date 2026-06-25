from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional
from data.database import DailySnapshot, Trade, get_session
from logs.logger import get_logger
log = get_logger(__name__)

class PerformanceAnalytics:
    def get_all_trades(self, is_paper=True):
        try:
            with get_session() as session:
                trades = session.query(Trade).filter_by(status="CLOSED").order_by(Trade.close_time).all()
                return [self._to_dict(t) for t in trades]
        except Exception as e:
            log.error("analytics_query_failed",error=str(e)); return []

    def get_open_trades(self, is_paper=True):
        try:
            with get_session() as session:
                trades = session.query(Trade).filter_by(status="OPEN").all()
                return [self._to_dict(t) for t in trades]
        except Exception as e:
            log.error("analytics_open_failed",error=str(e)); return []

    def get_summary_stats(self, is_paper=True):
        trades = self.get_all_trades(is_paper)
        if not trades:
            return {"total_trades":0,"win_rate_pct":0.0,"profit_factor":0.0,"total_pnl":0.0,
                    "avg_r_multiple":0.0,"max_drawdown_pct":0.0,"sharpe_ratio":0.0,
                    "best_trade":0.0,"worst_trade":0.0,"avg_win":0.0,"avg_loss":0.0,
                    "consecutive_losses":0,"total_trades_today":0,"pnl_today":0.0,
                    "winning_trades":0,"losing_trades":0}
        wins = [t for t in trades if (t["pnl"] or 0)>0]
        losses = [t for t in trades if (t["pnl"] or 0)<=0]
        pnls = [t["pnl"] or 0 for t in trades]
        rs = [t["r_multiple"] or 0 for t in trades]
        gp = sum(p for p in pnls if p>0)
        gl = abs(sum(p for p in pnls if p<=0))
        pf = round(gp/gl,3) if gl>0 else float("inf")
        max_c = cur_c = 0
        for t in trades:
            if (t["pnl"] or 0)<=0: cur_c+=1; max_c=max(max_c,cur_c)
            else: cur_c=0
        today = datetime.utcnow().strftime("%Y-%m-%d")
        today_t = [t for t in trades if (t.get("close_time","") or "")[:10]==today]
        return {"total_trades":len(trades),"winning_trades":len(wins),"losing_trades":len(losses),
                "win_rate_pct":round(len(wins)/len(trades)*100,1),"profit_factor":pf,
                "total_pnl":round(sum(pnls),2),"avg_r_multiple":round(sum(rs)/len(rs),3) if rs else 0,
                "best_trade":round(max(pnls),2),"worst_trade":round(min(pnls),2),
                "avg_win":round(sum(t["pnl"] or 0 for t in wins)/len(wins),2) if wins else 0,
                "avg_loss":round(sum(t["pnl"] or 0 for t in losses)/len(losses),2) if losses else 0,
                "consecutive_losses":max_c,"total_trades_today":len(today_t),
                "pnl_today":round(sum(t["pnl"] or 0 for t in today_t),2)}

    def get_equity_curve(self, initial_balance=100000.0, is_paper=True):
        trades = self.get_all_trades(is_paper)
        if not trades:
            return [{"date":datetime.utcnow().strftime("%Y-%m-%d"),"equity":initial_balance}]
        balance = initial_balance
        curve = [{"date":(trades[0].get("open_time","") or "")[:10],"equity":balance}]
        for t in trades:
            balance += (t["pnl"] or 0)
            curve.append({"date":(t.get("close_time",datetime.utcnow().isoformat()) or "")[:10],"equity":round(balance,2)})
        return curve

    def get_trades_by_instrument(self, is_paper=True):
        trades = self.get_all_trades(is_paper)
        result = {}
        for t in trades:
            inst = t["instrument"]
            if inst not in result: result[inst]={"trades":0,"wins":0,"pnl":0.0}
            result[inst]["trades"]+=1
            if (t["pnl"] or 0)>0: result[inst]["wins"]+=1
            result[inst]["pnl"]=round(result[inst]["pnl"]+(t["pnl"] or 0),2)
        for inst in result:
            n=result[inst]["trades"]
            result[inst]["win_rate"]=round(result[inst]["wins"]/n*100,1) if n>0 else 0
        return result

    def get_daily_snapshots(self, days=30):
        try:
            cutoff=(datetime.utcnow()-timedelta(days=days)).strftime("%Y-%m-%d")
            with get_session() as session:
                snaps=session.query(DailySnapshot).filter(DailySnapshot.date>=cutoff).order_by(DailySnapshot.date).all()
                return [{"date":s.date,"pnl":s.daily_pnl,"pnl_pct":s.daily_pnl_pct,"trades":s.trades_closed,"balance":s.closing_balance} for s in snaps]
        except Exception as e:
            log.error("snapshots_failed",error=str(e)); return []

    @staticmethod
    def _to_dict(t):
        return {"id":t.id,"instrument":t.instrument,"direction":t.direction,
                "strategy_id":t.strategy_id,"entry_price":t.entry_price,"exit_price":t.exit_price,
                "stop_loss":t.stop_loss,"take_profit":t.take_profit,"lot_size":t.lot_size,
                "pnl":t.pnl,"r_multiple":t.r_multiple,"status":t.status,
                "close_reason":t.close_reason,
                "open_time":t.open_time.isoformat() if t.open_time else None,
                "close_time":t.close_time.isoformat() if t.close_time else None,
                "is_paper":t.is_paper}
