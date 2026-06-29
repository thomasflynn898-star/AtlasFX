"""
paper_trading/agent.py
AtlasFX Professional Edition v2
Trailing stops + Invalidation + Telegram + Weekly reports
"""
from __future__ import annotations
from datetime import datetime
from broker.oanda import OANDABroker
from config.settings import settings
from data.database import init_db
from execution.engine import ExecutionConfig, ExecutionEngine
from filters.correlation_filter import CorrelationFilter
from filters.news_filter import NewsFilter
from filters.regime_detector import RegimeDetector
from filters.position_sizer import AdaptivePositionSizer
from filters.trade_manager import TradeManager
from journal.trade_journal import TradeJournal
from logs.logger import get_logger
from notifications.engine import NotificationEngine
from reporting.weekly_report import WeeklyReportGenerator
from risk.engine import RiskEngine
from strategies.strategy_orb import ORBStrategy
from strategies.strategy_ny_orb import NYORBStrategy
from strategies.strategy_ema_pullback import EMAPullbackStrategy
from monitoring.health_check import HealthCheck
log = get_logger(__name__)

BLACKLISTED = ["EUR_CAD"]

ACTIVE_INSTRUMENTS = [
    "EUR_USD","GBP_USD","USD_JPY","USD_CHF","AUD_USD","USD_CAD","NZD_USD",
    "EUR_GBP","EUR_JPY","EUR_CHF","EUR_AUD","EUR_CAD","GBP_JPY","GBP_CHF",
    "GBP_AUD","GBP_CAD","AUD_JPY","AUD_CAD","AUD_CHF","AUD_NZD","CAD_JPY",
    "CHF_JPY","NZD_JPY","NZD_USD","XAU_USD","XAG_USD",
]
PIP_SIZE_MAP = {
    "EUR_USD":0.0001,"GBP_USD":0.0001,"USD_CHF":0.0001,"AUD_USD":0.0001,
    "USD_CAD":0.0001,"NZD_USD":0.0001,"EUR_GBP":0.0001,"EUR_CHF":0.0001,
    "EUR_AUD":0.0001,"EUR_CAD":0.0001,"GBP_CHF":0.0001,"GBP_AUD":0.0001,
    "GBP_CAD":0.0001,"AUD_CAD":0.0001,"AUD_CHF":0.0001,"AUD_NZD":0.0001,
    "USD_JPY":0.01,"EUR_JPY":0.01,"GBP_JPY":0.01,"AUD_JPY":0.01,
    "CAD_JPY":0.01,"CHF_JPY":0.01,"NZD_JPY":0.01,
    "XAU_USD":0.01,"XAG_USD":0.01,
}
ACTIVE_STRATEGIES = [
    ORBStrategy,
    NYORBStrategy,
    EMAPullbackStrategy,
]

class PaperTradingAgent:
    def __init__(self):
        log.info("agent_initialising")
        init_db()
        if not settings.oanda_api_key:
            raise RuntimeError("OANDA_API_KEY not set.")
        self._broker = OANDABroker(
            api_key=settings.oanda_api_key,
            account_id=settings.oanda_account_id,
            environment=settings.oanda_environment.value,
        )
        if not self._broker.test_connection():
            raise RuntimeError("Could not connect to OANDA.")
        account = self._broker.get_account()
        self._starting_balance = account.nav
        self._daily_start_balance = account.nav
        self._risk_engine = RiskEngine(
            account_balance=account.nav,
            risk_per_trade_pct=settings.risk_per_trade_pct,
        )
        self._execution_engine = ExecutionEngine(
            broker=self._broker, risk_engine=self._risk_engine,
            config=ExecutionConfig(is_paper_mode=False),
        )
        self._news = NewsFilter()
        self._correlation = CorrelationFilter()
        self._regime = RegimeDetector()
        self._sizer = AdaptivePositionSizer()
        self._trade_manager = TradeManager(self._broker)
        self._journal = TradeJournal()
        self._notifier = NotificationEngine.from_settings()
        self._reporter = WeeklyReportGenerator()
        self._health = HealthCheck(broker=self._broker, telegram=None)
        self._telegram = None
        self._setup_telegram()
        self._open_positions: dict[str, dict] = {}
        self._scan_count = 0
        self._news.refresh()
        self._sync_open_positions()
        log.info("agent_initialised", balance=round(account.nav,2),
                 currency=account.currency, mode="PROFESSIONAL_V2",
                 strategies=len(ACTIVE_STRATEGIES), instruments=len(ACTIVE_INSTRUMENTS),
                 telegram="enabled" if self._telegram else "disabled")

    def _setup_telegram(self):
        try:
            if settings.telegram_bot_token and settings.telegram_chat_id:
                from telegram.bot import TelegramBot
                self._telegram = TelegramBot(settings.telegram_bot_token, settings.telegram_chat_id)
                self._register_commands()
                self._telegram.start_polling()
                log.info("telegram_enabled")
        except Exception as e:
            log.warning("telegram_setup_failed", error=str(e))

    def _register_commands(self):
        if not self._telegram: return
        def cmd_weekly(args): return self._reporter.generate()
        def cmd_health(args):
            try:
                from monitoring.health_monitor import HealthMonitor
                return HealthMonitor().get_status_report()
            except Exception as e: return f"Health error: {e}"
        self._telegram.register_handler("weekly", cmd_weekly)
        self._telegram.register_handler("health", cmd_health)
        if hasattr(self._telegram, "set_broker"):
            self._telegram.set_broker(self._broker)


    def start(self):
        try:
            from apscheduler.schedulers.blocking import BlockingScheduler
        except ImportError:
            print("\n Run: pip install apscheduler\n"); return
        if self._telegram: self._telegram.agent_started()
        scheduler = BlockingScheduler(timezone="UTC")
        scheduler.add_job(self._scan_and_trade,"cron",minute="1,16,31,46",id="scan",max_instances=1,coalesce=True)
        scheduler.add_job(self._monitor_positions,"interval",minutes=5,id="monitor",max_instances=1,coalesce=True)
        scheduler.add_job(self._send_daily_report,"cron",hour=22,minute=0,id="report")
        scheduler.add_job(self._reset_daily_balance,"cron",hour=0,minute=1,id="reset")
        scheduler.add_job(self._news.refresh,"interval",hours=6,id="news_refresh")
        scheduler.add_job(self._send_weekly_report,"cron",day_of_week="mon",hour=8,minute=0,id="weekly")
        scheduler.add_job(lambda:self._health.send_health_report(),"cron",hour="7,10,13,16",minute=0,id="health")
        print("\n" + "="*58)
        print(f"  AtlasFX Professional Edition v2")
        print(f"  Balance   : {self._starting_balance:,.2f}")
        print(f"  Signals   : H4 + H1 + M15 MTF")
        print(f"  Trailing  : Breakeven + Trail + Invalidation")
        print(f"  Telegram  : {'✓' if self._telegram else '✗ Add token to .env'}")
        print(f"  Strategies: {len(ACTIVE_STRATEGIES)} | Pairs: {len(ACTIVE_INSTRUMENTS)}")
        print(f"  Scans     : every 15 minutes")
        print("="*58 + "\n")
        self._scan_and_trade()
        try: scheduler.start()
        except KeyboardInterrupt: self.stop("KeyboardInterrupt")

    def stop(self, reason="Manual stop"):
        if self._telegram: self._telegram.agent_stopped(reason); self._telegram.stop_polling()
        log.info("agent_stopped", reason=reason)

    def _sync_open_positions(self):
        from data.database import get_session, Trade
        try: oanda_open={str(t.trade_id):t for t in self._broker.get_open_trades()}
        except Exception as e: log.error("oanda_sync_failed",error=str(e)); oanda_open={}
        try:
            with get_session() as s:
                for t in s.query(Trade).filter_by(status="OPEN").all():
                    tid=str(t.id); pip=PIP_SIZE_MAP.get(t.instrument,0.0001)
                    if tid in oanda_open:
                        self._open_positions[tid]={"instrument":t.instrument,"direction":t.direction,
                            "entry_price":t.entry_price,"stop_loss":t.stop_loss,"current_sl":t.stop_loss,
                            "take_profit":t.take_profit,"strategy_id":t.strategy_id or "UNKNOWN",
                            "pip_size":pip,"opened_at":t.open_time or datetime.utcnow(),
                            "h4_bias":"?","h1_trend":"?","regime":"?","risk_pct":0.5}
                        log.info("position_sync_active",trade_id=tid,instrument=t.instrument)
                    else:
                        try: cur=self._broker.get_price(t.instrument).mid
                        except: cur=t.entry_price
                        cr="stop_loss" if abs(cur-t.stop_loss)<abs(cur-t.take_profit) else "take_profit"
                        ep=t.stop_loss if cr=="stop_loss" else t.take_profit
                        pp=(ep-t.entry_price) if t.direction=="BUY" else (t.entry_price-ep)
                        pnl=round(pp/pip*pip*(t.lot_size or 10000),2)
                        rd=abs(t.entry_price-t.stop_loss)
                        r=round(pp/rd,2) if rd>0 else 0
                        t.exit_price=ep;t.close_time=datetime.utcnow();t.close_reason=cr
                        t.status="CLOSED";t.pnl=pnl;t.r_multiple=r
                        log.info("position_sync_closed",trade_id=tid,instrument=t.instrument,pnl=pnl)
                        if self._telegram: self._telegram.trade_closed(t.instrument,t.direction,pnl,r,cr+" (restart)")
            if self._open_positions: log.info("positions_synced",count=len(self._open_positions))
        except Exception as e: log.error("position_sync_failed",error=str(e))

    def _scan_and_trade(self):
        self._scan_count+=1
        self._health.record_scan()
        log.info("agent_scan_start",scan=self._scan_count)
        if self._risk_engine.is_halted:
            log.warning("scan_halted",reason=self._risk_engine.halt_reason); return
        upcoming=self._news.get_upcoming_events(hours_ahead=2)
        if upcoming: log.info("upcoming_news",count=len(upcoming),next=upcoming[0].get("title","?"))
        for instrument in ACTIVE_INSTRUMENTS:
            if any(p.get("instrument")==instrument for p in self._open_positions.values()): continue
            if instrument in BLACKLISTED: continue
            safe,_=self._news.is_safe_to_trade(instrument)
            if not safe: continue
            corr_ok,_=self._correlation.can_open(instrument,"ANY",self._open_positions)
            if not corr_ok: continue
            try:
                h1=self._broker.get_candles_as_dataframe(instrument,"H1",100)
                regime=self._regime.detect(h1) if h1 is not None else "UNKNOWN"
                allowed=self._regime.get_allowed_strategies(regime)
            except: regime="UNKNOWN"; allowed=[cls.METADATA.strategy_id for cls in ACTIVE_STRATEGIES]
            pip=PIP_SIZE_MAP.get(instrument,0.0001)
            for StrategyClass in ACTIVE_STRATEGIES:
                # Use cached instance to preserve daily state (prevents duplicates)
                cache_key=f"{StrategyClass.__name__}_{pip}"
                if not hasattr(self,"_strat_cache"): self._strat_cache={}
                if cache_key not in self._strat_cache:
                    self._strat_cache[cache_key]=StrategyClass(pip_size=pip)
                strat=self._strat_cache[cache_key]
                if instrument not in strat.METADATA.instruments: continue
                try:
                    # ORB uses H1 data directly — bypass MTF engine
                    h1_data=self._broker.get_candles(instrument,"H1",250)
                    if not h1_data or len(h1_data)<strat.METADATA.min_history_bars: continue
                    import pandas as pd
                    df=pd.DataFrame(h1_data)
                    df.index=pd.to_datetime(df["time"])
                    df=df.rename(columns={"open":"Open","high":"High","low":"Low","close":"Close","volume":"Volume"})
                    df=df[["Open","High","Low","Close","Volume"]].astype(float).sort_index()
                    signal=strat.generate_signal(df,instrument,"H1")
                    if signal:
                        corr_ok,_=self._correlation.can_open(instrument,signal.direction,self._open_positions)
                        if not corr_ok: continue
                        signal.metadata=signal.metadata or {}
                        signal.metadata["regime"]=regime
                        self._open_positions["pending_"+instrument]={"instrument":instrument,"direction":signal.direction}
                        self._execute_signal(signal,instrument,pip)
                        self._open_positions.pop("pending_"+instrument,None)
                        break
                except Exception as e:
                    log.error("scan_error",instrument=instrument,strategy=strat.METADATA.strategy_id,error=str(e))
        log.info("agent_scan_complete",scan=self._scan_count,open_positions=len(self._open_positions))
        hour = datetime.utcnow().hour
        if hour == 14:
            log.info("london_session_complete",signals_today=self._health._signal_count,scan=self._scan_count)
            if self._telegram and self._health._signal_count == 0:
                self._telegram.send("London session closed — no signals fired today. Market conditions not met.", parse_mode="")
        if hour == 17:
            log.info("ny_session_complete",signals_today=self._health._signal_count,scan=self._scan_count)
            if self._telegram and self._health._signal_count == 0:
                self._telegram.send("NY session closed — no signals fired today.", parse_mode="")

    def _execute_signal(self, signal, instrument, pip_size):
        risk_pct=self._sizer.calculate_risk_pct(signal=signal,recent_trades=[],
            current_dd_pct=0.0,daily_dd_limit_pct=2.0,
            current_exposure_pct=len(self._open_positions)*0.5)
        original=self._risk_engine._configured_risk_pct
        self._risk_engine._configured_risk_pct=risk_pct
        risk_result=self._risk_engine.evaluate_signal(signal,current_open_exposure_pct=len(self._open_positions)*0.5)
        risk_result.risk_pct_override=risk_pct
        self._risk_engine._configured_risk_pct=original
        if not risk_result.approved: log.info("signal_rejected",reason=risk_result.reason); return
        result=self._execution_engine.execute(signal,risk_result)
        if result.success and result.order_result:
            try: balance=self._broker.get_account().nav
            except: balance=self._starting_balance
            trade_id=self._journal.record_execution(result,balance)
            if trade_id:
                self._open_positions[trade_id]={"instrument":instrument,"direction":signal.direction,
                    "entry_price":signal.entry_price if signal.entry_price>0 else result.order_result.entry_price,"stop_loss":signal.stop_loss,
                    "current_sl":signal.stop_loss,"take_profit":signal.take_profit,
                    "strategy_id":signal.strategy_id,"pip_size":pip_size,
                    "opened_at":datetime.utcnow(),"h4_bias":signal.metadata.get("h4_bias","?"),
                    "h1_trend":signal.metadata.get("h1_trend","?"),
                    "regime":signal.metadata.get("regime","?"),"risk_pct":risk_pct}
                if self._telegram:
                    meta=signal.metadata or {}
                    self._telegram.trade_opened(instrument,signal.direction,
                        result.order_result.entry_price,signal.stop_loss,signal.take_profit,
                        result.order_result.units,signal.strategy_id,risk_pct,
                        confidence=signal.confidence,
                        adx=meta.get("adx",0),
                        asian_range_pips=meta.get("asian_range_pips",meta.get("ny_range_pips",0)))
                log.info("trade_opened",trade_id=trade_id,instrument=instrument,
                         direction=signal.direction,strategy=signal.strategy_id,
                         risk_pct=risk_pct,confidence=signal.confidence)

    def _monitor_positions(self):
        if not self._open_positions: return
        for trade_id,pos in list(self._open_positions.items()):
            try:
                price=self._broker.get_price(pos["instrument"])
                cur=price.mid; sl=pos["stop_loss"]; tp=pos["take_profit"]
                current_sl=pos.get("current_sl",sl); entry=pos["entry_price"]
                d=pos["direction"]; pip=pos["pip_size"]
                # Telegram trade update — max once per hour per trade
                if self._telegram:
                    try:
                        from datetime import datetime as _dt
                        if not hasattr(self,"_last_update"): self._last_update={}
                        last=self._last_update.get(trade_id,0)
                        now_ts=_dt.utcnow().timestamp()
                        if now_ts-last>=3600:  # 1 hour minimum between updates
                            self._last_update[trade_id]=now_ts
                            cur2=self._broker.get_price(pos["instrument"]).mid
                            pips=(cur2-pos["entry_price"])/pos["pip_size"] if pos["direction"]=="BUY" else (pos["entry_price"]-cur2)/pos["pip_size"]
                            score=self._telegram.trade_update(
                                instrument=pos["instrument"],direction=pos["direction"],
                                entry=pos["entry_price"],current=cur2,
                                sl=pos.get("current_sl",pos["stop_loss"]),
                                tp=pos["take_profit"],pnl_pips=pips,
                                adx=pos.get("adx",0))
                            if score<4 and pips<-2:
                                log.warning("low_confidence_alert",instrument=pos["instrument"],score=score)
                    except Exception as _te:
                        pass
                action=self._trade_manager.evaluate(trade_id,pos)
                if action["close"]:
                    self._broker.close_trade(trade_id)
                    pp=(cur-entry) if d=="BUY" else (entry-cur)
                    rd=abs(entry-sl); r=round(pp/rd,2) if rd>0 else 0
                    pnl=round(pp/pip*pip*10000,2)
                    try: bal=self._broker.get_account().nav
                    except: bal=self._starting_balance
                    self._journal.record_close(trade_id,cur,action["close_reason"],bal)
                    self._risk_engine.update_equity(bal)
                    if self._telegram: self._telegram.trade_closed(pos["instrument"],d,pnl,r,action["close_reason"],entry,cur)
                    log.info("trade_closed_invalidation",trade_id=trade_id,reason=action["close_reason"])
                    del self._open_positions[trade_id]; continue
                if action["modify_sl"] and action["new_sl"]:
                    new_sl=action["new_sl"]
                    if self._broker.modify_trade(trade_id,stop_loss=new_sl):
                        pos["current_sl"]=new_sl
                        if self._telegram:
                            pr=abs(cur-entry)/abs(entry-sl) if sl!=entry else 0
                            self._telegram.sl_moved(pos["instrument"],current_sl,new_sl,pr)
                close_reason=exit_price=None
                if d=="BUY":
                    if cur<=current_sl: close_reason,exit_price="stop_loss",current_sl
                    elif cur>=tp: close_reason,exit_price="take_profit",tp
                else:
                    if cur>=current_sl: close_reason,exit_price="stop_loss",current_sl
                    elif cur<=tp: close_reason,exit_price="take_profit",tp
                if close_reason:
                    pp=(exit_price-entry) if d=="BUY" else (entry-exit_price)
                    rd=abs(entry-sl); r=round(pp/rd,2) if rd>0 else 0
                    pnl=round(pp/pip*pip*10000,2)
                    try: bal=self._broker.get_account().nav
                    except: bal=self._starting_balance
                    self._journal.record_close(trade_id,exit_price,close_reason,bal)
                    self._risk_engine.update_equity(bal)
                    if self._telegram: self._telegram.trade_closed(pos["instrument"],d,pnl,r,close_reason,entry,exit_price)
                    log.info("trade_closed",trade_id=trade_id,instrument=pos["instrument"],reason=close_reason,r=r,pnl=pnl)
                    del self._open_positions[trade_id]
            except Exception as e:
                log.error("monitor_error",trade_id=trade_id,error=str(e))

    def _send_daily_report(self):
        date=datetime.utcnow().strftime("%Y-%m-%d")
        stats=self._journal.get_daily_stats(date)
        try: balance=self._broker.get_account().nav
        except: balance=self._starting_balance
        if self._telegram:
            self._telegram.daily_report(date,stats.get("trades",0),stats.get("wins",0),
                stats.get("losses",0),stats.get("pnl",0.0),stats.get("win_rate",0.0),balance)
        self._journal.save_daily_snapshot(date,self._daily_start_balance,balance)

    def _send_weekly_report(self):
        report=self._reporter.generate()
        if self._telegram: self._telegram.send(report)
        log.info("weekly_report_sent")

    def _reset_daily_balance(self):
        try:
            a=self._broker.get_account()
            self._daily_start_balance=a.nav
            self._risk_engine.resume_trading()
        except Exception as e: log.error("daily_reset_failed",error=str(e))

    def run_single_scan(self):
        self._scan_and_trade()
        return {"scan_count":self._scan_count,"open_positions":len(self._open_positions),
                "risk_halted":self._risk_engine.is_halted,"positions":list(self._open_positions.keys()),
                "mode":"PROFESSIONAL_V2"}
