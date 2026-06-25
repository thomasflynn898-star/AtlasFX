from __future__ import annotations
from datetime import datetime, timedelta
from data.database import Trade, get_session
from logs.logger import get_logger
log = get_logger(__name__)

class WeeklyReportGenerator:
    def generate(self, week_start=None, week_end=None):
        if week_end is None: week_end=datetime.utcnow()
        if week_start is None: week_start=week_end-timedelta(days=7)
        try:
            trades=self._get_week_trades(week_start,week_end)
            return self._format_report(trades,week_start,week_end)
        except Exception as e:
            log.error("weekly_report_failed",error=str(e))
            return "Report generation failed: "+str(e)

    def _get_week_trades(self, start, end):
        with get_session() as s:
            trades=s.query(Trade).filter(
                Trade.status=="CLOSED",
                Trade.close_time>=start,
                Trade.close_time<=end,
            ).order_by(Trade.close_time).all()
            return [{"instrument":t.instrument,"direction":t.direction,
                     "strategy_id":t.strategy_id,"pnl":t.pnl or 0,
                     "r_multiple":t.r_multiple or 0,"close_reason":t.close_reason}
                    for t in trades]

    def _format_report(self, trades, start, end):
        week=start.strftime("%d %b")+" - "+end.strftime("%d %b %Y")
        if not trades:
            lines=["Weekly Report","Week: "+week,"","No closed trades this week.","Agent scanning 24/7."]
            return chr(10).join(lines)
        total=len(trades)
        wins=[t for t in trades if t["pnl"]>0]
        losses=[t for t in trades if t["pnl"]<=0]
        pnl=sum(t["pnl"] for t in trades)
        wr=round(len(wins)/total*100,1) if total>0 else 0
        gp=sum(t["pnl"] for t in wins) if wins else 0
        gl=abs(sum(t["pnl"] for t in losses)) if losses else 0.001
        pf=round(gp/gl,3)
        avg_r=round(sum(t["r_multiple"] for t in trades)/total,2) if total>0 else 0
        best=max(trades,key=lambda x:x["pnl"])
        worst=min(trades,key=lambda x:x["pnl"])
        by_strat={}
        for t in trades:
            s=t["strategy_id"] or "Unknown"
            if s not in by_strat: by_strat[s]={"trades":0,"wins":0,"pnl":0.0}
            by_strat[s]["trades"]+=1
            if t["pnl"]>0: by_strat[s]["wins"]+=1
            by_strat[s]["pnl"]+=t["pnl"]
        by_inst={}
        for t in trades:
            i=t["instrument"]
            if i not in by_inst: by_inst[i]={"trades":0,"pnl":0.0}
            by_inst[i]["trades"]+=1; by_inst[i]["pnl"]+=t["pnl"]
        sign="+" if pnl>=0 else ""
        lines=["AtlasFX Weekly Report","Week: "+week,"",
               "SUMMARY",
               "Trades: "+str(total)+" (W:"+str(len(wins))+" L:"+str(len(losses))+")",
               "Win Rate: "+str(wr)+"%",
               "PnL: "+sign+str(round(pnl,2)),
               "Profit Factor: "+str(pf),
               "Avg R: "+str(avg_r)+"R","",
               "BEST: "+best["instrument"]+" "+best["direction"]+" +"+str(round(best["pnl"],2)),
               "WORST: "+worst["instrument"]+" "+worst["direction"]+" "+str(round(worst["pnl"],2)),
               "","BY STRATEGY"]
        for sid,d in sorted(by_strat.items(),key=lambda x:x[1]["pnl"],reverse=True):
            wr2=round(d["wins"]/d["trades"]*100) if d["trades"]>0 else 0
            s2="+" if d["pnl"]>=0 else ""
            short=sid.replace("_H1_V1","").replace("_"," ")
            lines.append(short+": "+str(d["trades"])+"t "+str(wr2)+"% "+s2+str(round(d["pnl"],2)))
        lines.append("")
        lines.append("BY INSTRUMENT")
        for inst,d in sorted(by_inst.items(),key=lambda x:x[1]["pnl"],reverse=True)[:5]:
            s3="+" if d["pnl"]>=0 else ""
            lines.append(inst+": "+str(d["trades"])+"t "+s3+str(round(d["pnl"],2)))
        lines.extend(["","Agent running 24/7 on VPS","ML scorer coming next month"])
        return chr(10).join(lines)
