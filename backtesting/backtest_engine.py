import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd

@dataclass
class BacktestTrade:
    instrument: str; strategy_id: str; direction: str
    entry_price: float; stop_loss: float; take_profit: float
    entry_time: datetime; exit_price: float = 0.0
    exit_time: Optional[datetime] = None; close_reason: str = ""
    pnl_pips: float = 0.0; r_multiple: float = 0.0
    h4_bias: str = ""; h1_trend: str = ""; regime: str = ""

@dataclass
class BacktestResult:
    total_trades: int = 0; winning_trades: int = 0; losing_trades: int = 0
    win_rate: float = 0.0; total_pnl_pips: float = 0.0; profit_factor: float = 0.0
    avg_r: float = 0.0; best_trade_pips: float = 0.0; worst_trade_pips: float = 0.0
    max_consecutive_losses: int = 0; trades: list = field(default_factory=list)
    by_strategy: dict = field(default_factory=dict)
    by_instrument: dict = field(default_factory=dict)
    by_regime: dict = field(default_factory=dict)

class BacktestEngine:
    def __init__(self, broker, initial_balance=100000.0):
        self._broker = broker; self._initial_balance = initial_balance

    def run(self, instruments, strategy_classes, months=12, pip_map=None):
        pip_map = pip_map or {}
        all_trades = []
        total = len(instruments) * len(strategy_classes)
        done = 0
        print(f"\n{'='*60}\n  AtlasFX Backtest — Last {months} months\n  {len(instruments)} pairs x {len(strategy_classes)} strategies\n{'='*60}\n")
        for inst in instruments:
            pip_size = pip_map.get(inst, 0.0001)
            try:
                h4 = self._fetch(inst,"H4",months); h1 = self._fetch(inst,"H1",months); m15 = self._fetch(inst,"M15",months)
            except Exception as e:
                print(f"  ✗ {inst}: {e}"); continue
            if h4 is None or len(h4)<200: print(f"  ✗ {inst}: no data"); continue
            for SC in strategy_classes:
                strat = SC(pip_size=pip_size); done += 1
                if inst not in strat.METADATA.instruments: continue
                try:
                    trades = self._run_strat(inst,strat,pip_size,h4,h1,m15)
                    all_trades.extend(trades)
                    if trades: print(f"  ✓ {inst:12} / {strat.METADATA.strategy_id.replace('_H1_V1',''):<22} {len(trades)} signals")
                except Exception as e:
                    print(f"  ✗ {inst} {strat.METADATA.strategy_id}: {e}")
                if done % 15 == 0: print(f"  ... {int(done/total*100)}% complete")
        return self._stats(all_trades)

    def _fetch(self, inst, gran, months):
        counts = {"H4":min(months*180,5000),"H1":min(months*720,5000),"M15":min(months*2880,5000)}
        candles = self._broker.get_candles(inst, gran, counts.get(gran,5000))
        if not candles: return None
        df = pd.DataFrame(candles)
        df.index = pd.to_datetime(df['time'])
        df = df.rename(columns={'open':'Open','high':'High','low':'Low','close':'Close','volume':'Volume'})
        return df[['Open','High','Low','Close','Volume']].astype(float).sort_index()

    def _run_strat(self, inst, strat, pip_size, h4, h1, m15):
        from strategies.mtf_engine import get_h4_bias, get_h1_trend, bias_matches_signal
        from filters.regime_detector import RegimeDetector
        rd = RegimeDetector(); trades = []; min_bars = max(strat.METADATA.min_history_bars,50)
        for i in range(min_bars, len(m15)-10, 4):
            bar_time = m15.index[i]
            # Session filter - London and NY only
            if not(7<=bar_time.hour<12 or 13<=bar_time.hour<18): continue
            h4w = h4[h4.index<=bar_time]; h1w = h1[h1.index<=bar_time]
            if len(h4w)<201 or len(h1w)<52: continue
            h4b = get_h4_bias(h4w)
            if h4b=="NEUTRAL": continue
            h1t = get_h1_trend(h1w)
            if h1t=="NEUTRAL" or h4b!=h1t: continue
            try:
                regime = rd.detect(h1w.iloc[-100:])
                if strat.METADATA.strategy_id not in rd.get_allowed_strategies(regime): continue
            except: regime="UNKNOWN"
            try:
                sig = strat.generate_signal(data=m15.iloc[:i], instrument=inst, timeframe="M15")
            except: continue
            if sig is None: continue
            if not bias_matches_signal(h4b,h1t,sig.direction): continue
            if abs(sig.entry_price-sig.stop_loss)<pip_size*2: continue
            t = self._sim(inst,strat.METADATA.strategy_id,sig.direction,sig.entry_price,sig.stop_loss,sig.take_profit,bar_time,m15.iloc[i:i+200],pip_size,h4b,h1t,regime)
            if t: trades.append(t)
        return trades

    def _sim(self, inst, sid, direction, entry, sl, tp, etime, future, pip_size, h4b, h1t, regime):
        rp = abs(entry-sl)/pip_size; rwp = abs(tp-entry)/pip_size
        if rp<=0 or rwp<=0: return None
        for idx,row in future.iterrows():
            if direction=="BUY":
                if row['Low']<=sl: return BacktestTrade(inst,sid,direction,entry,sl,tp,etime,sl,idx,"stop_loss",round(-rp,1),-1.0,h4b,h1t,regime)
                elif row['High']>=tp: return BacktestTrade(inst,sid,direction,entry,sl,tp,etime,tp,idx,"take_profit",round(rwp,1),round(rwp/rp,2),h4b,h1t,regime)
            else:
                if row['High']>=sl: return BacktestTrade(inst,sid,direction,entry,sl,tp,etime,sl,idx,"stop_loss",round(-rp,1),-1.0,h4b,h1t,regime)
                elif row['Low']<=tp: return BacktestTrade(inst,sid,direction,entry,sl,tp,etime,tp,idx,"take_profit",round(rwp,1),round(rwp/rp,2),h4b,h1t,regime)
        return None

    def _stats(self, trades):
        r = BacktestResult(); r.trades = trades; r.total_trades = len(trades)
        if not trades: return r
        wins=[t for t in trades if t.pnl_pips>0]; losses=[t for t in trades if t.pnl_pips<=0]
        r.winning_trades=len(wins); r.losing_trades=len(losses)
        r.win_rate=len(wins)/len(trades)*100; r.total_pnl_pips=sum(t.pnl_pips for t in trades)
        gp=sum(t.pnl_pips for t in wins) if wins else 0
        gl=abs(sum(t.pnl_pips for t in losses)) if losses else 0.001
        r.profit_factor=round(gp/gl,3); r.avg_r=round(sum(t.r_multiple for t in trades)/len(trades),3)
        r.best_trade_pips=max(t.pnl_pips for t in trades); r.worst_trade_pips=min(t.pnl_pips for t in trades)
        consec=0; mc=0
        for t in sorted(trades,key=lambda x:x.entry_time):
            if t.pnl_pips<=0: consec+=1; mc=max(mc,consec)
            else: consec=0
        r.max_consecutive_losses=mc
        for t in trades:
            for key,val in [('by_strategy',t.strategy_id),('by_instrument',t.instrument),('by_regime',t.regime)]:
                d=getattr(r,key)
                if val not in d: d[val]={'trades':0,'wins':0,'pnl':0.0}
                d[val]['trades']+=1
                if t.pnl_pips>0: d[val]['wins']+=1
                d[val]['pnl']+=t.pnl_pips
        return r

def print_report(result):
    if not result.total_trades:
        print("No trades generated in backtest period."); return
    print(f"\n{'='*60}")
    print(f"  ATLASFX BACKTEST RESULTS")
    print(f"{'='*60}")
    print(f"  Total Trades      : {result.total_trades}")
    print(f"  Win Rate          : {result.win_rate:.1f}%")
    print(f"  Total P&L (pips)  : {result.total_pnl_pips:+.1f}")
    print(f"  Profit Factor     : {result.profit_factor}")
    print(f"  Avg R             : {result.avg_r:+.3f}R")
    print(f"  Best Trade        : +{result.best_trade_pips:.1f} pips")
    print(f"  Worst Trade       : {result.worst_trade_pips:.1f} pips")
    print(f"  Max Consec Losses : {result.max_consecutive_losses}")
    print(f"\n  BY STRATEGY")
    print(f"  {'-'*54}")
    for sid,s in sorted(result.by_strategy.items(),key=lambda x:x[1]['pnl'],reverse=True):
        wr=s['wins']/s['trades']*100 if s['trades'] else 0
        print(f"  {sid.replace('_H1_V1','')[:26]:<26} {s['trades']:>4}t  {wr:>5.1f}%  {s['pnl']:>+8.1f}p")
    print(f"\n  TOP INSTRUMENTS")
    print(f"  {'-'*54}")
    for inst,s in sorted(result.by_instrument.items(),key=lambda x:x[1]['pnl'],reverse=True)[:10]:
        wr=s['wins']/s['trades']*100 if s['trades'] else 0
        print(f"  {inst:<14} {s['trades']:>4}t  {wr:>5.1f}%  {s['pnl']:>+8.1f}p")
    print(f"\n  BY REGIME")
    print(f"  {'-'*54}")
    for regime,s in sorted(result.by_regime.items(),key=lambda x:x[1]['pnl'],reverse=True):
        wr=s['wins']/s['trades']*100 if s['trades'] else 0
        print(f"  {regime:<22} {s['trades']:>4}t  {wr:>5.1f}%  {s['pnl']:>+8.1f}p")
    print(f"\n{'='*60}\n")

if __name__=="__main__":
    from broker.oanda import OANDABroker
    from config.settings import settings
    from strategies.strategy_multi_confluence import MultiConfluenceStrategy
    from strategies.strategy_suite import (EMACrossoverStrategy,BollingerSqueezeStrategy,
        RSIMeanReversionStrategy,DoubleTopBottomStrategy,SupportResistanceBreakoutStrategy,LondonOpenBreakoutStrategy)
    INSTRUMENTS=["EUR_USD","GBP_USD","USD_JPY","AUD_USD","USD_CAD","EUR_JPY","GBP_JPY","EUR_GBP","AUD_JPY","XAU_USD","USD_CHF","NZD_USD","EUR_CHF","GBP_CHF","CAD_JPY"]
    PIP_MAP={"EUR_USD":0.0001,"GBP_USD":0.0001,"USD_CHF":0.0001,"AUD_USD":0.0001,"USD_CAD":0.0001,"NZD_USD":0.0001,"EUR_GBP":0.0001,"EUR_CHF":0.0001,"GBP_CHF":0.0001,"USD_JPY":0.01,"EUR_JPY":0.01,"GBP_JPY":0.01,"AUD_JPY":0.01,"CAD_JPY":0.01,"XAU_USD":0.01}
    STRATEGIES=[MultiConfluenceStrategy,EMACrossoverStrategy,BollingerSqueezeStrategy,RSIMeanReversionStrategy,DoubleTopBottomStrategy,SupportResistanceBreakoutStrategy,LondonOpenBreakoutStrategy]
    broker=OANDABroker(api_key=settings.oanda_api_key,account_id=settings.oanda_account_id,environment=settings.oanda_environment.value)
    result=BacktestEngine(broker).run(INSTRUMENTS,STRATEGIES,months=12,pip_map=PIP_MAP)
    print_report(result)
