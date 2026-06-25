from __future__ import annotations
import math
from datetime import datetime
from typing import Optional
import pandas as pd
from indicators.technical import atr, bollinger_bands, ema, rsi
from logs.logger import get_logger
from strategies.base import BaseStrategy, StrategyMetadata, TradeSignal
log = get_logger(__name__)

ALL_INSTRUMENTS = ["EUR_USD","GBP_USD","USD_JPY","USD_CHF","AUD_USD","USD_CAD","NZD_USD","EUR_GBP","EUR_JPY","EUR_CHF","EUR_AUD","EUR_CAD","GBP_JPY","GBP_CHF","GBP_AUD","GBP_CAD","AUD_JPY","AUD_CAD","AUD_CHF","AUD_NZD","CAD_JPY","CHF_JPY","NZD_JPY","NZD_USD","XAU_USD","XAG_USD"]

def _in_session(t, ls=7, le=12, ns=13, ne=18):
    if not hasattr(t,"hour"): return True, False
    h=t.hour; il=ls<=h<le; iny=ns<=h<ne; return il or iny, il

def _no_fri(t):
    return not (hasattr(t,"weekday") and t.weekday()==4 and hasattr(t,"hour") and t.hour>=15)

def _f(v):
    try: x=float(v); return None if math.isnan(x) or math.isinf(x) else x
    except: return None

def _sig(sid,inst,d,e,sl,tp,tf,bt,conf,meta):
    try:
        return TradeSignal(strategy_id=sid,instrument=inst,direction=d,
            entry_price=round(e,5),stop_loss=round(sl,5),take_profit=round(tp,5),
            confidence=conf,timeframe=tf,
            timestamp=bt if isinstance(bt,datetime) else datetime.utcnow(),metadata=meta)
    except: return None

class EMACrossoverStrategy(BaseStrategy):
    METADATA = StrategyMetadata(strategy_id="EMA_CROSSOVER_H1_V1",name="EMA Crossover H1",version="1.0.0",
        description="9/21 EMA cross filtered by 200 EMA trend and session.",instruments=ALL_INSTRUMENTS,timeframes=["H1"],min_history_bars=220)
    def __init__(self,pip_size=0.0001,sl_atr=1.5,tp_atr=2.5):
        super().__init__(); self.pip_size=pip_size; self.sl_atr=sl_atr; self.tp_atr=tp_atr
    def generate_signal(self,data,instrument,timeframe,current_bar_index=-1):
        if not self.validate_data(data): return None
        bt=data.index[-1]; ins,il=_in_session(bt)
        if not ins or not _no_fri(bt): return None
        c=data["Close"]; h=data["High"]; l=data["Low"]
        e9=ema(c,9); e21=ema(c,21); e200=ema(c,200); a=atr(h,l,c,14)
        if len(e9)<2: return None
        v=[_f(e9.iloc[-1]),_f(e21.iloc[-1]),_f(e200.iloc[-1]),_f(a.iloc[-1])]
        if any(x is None for x in v) or v[3]<=0: return None
        ce9,ce21,ce200,ca=v; pe9=_f(e9.iloc[-2]); pe21=_f(e21.iloc[-2])
        if pe9 is None or pe21 is None: return None
        cc=float(c.iloc[-1])
        bull=pe9<pe21 and ce9>ce21 and cc>ce200
        bear=pe9>pe21 and ce9<ce21 and cc<ce200
        if not bull and not bear: return None
        d="BUY" if bull else "SELL"
        e=cc; sl=e-ca*self.sl_atr if d=="BUY" else e+ca*self.sl_atr
        tp=e+ca*self.tp_atr if d=="BUY" else e-ca*self.tp_atr
        return _sig(self.METADATA.strategy_id,instrument,d,e,sl,tp,timeframe,bt,0.65,{"atr":round(ca,5),"session":"london" if il else "ny"})

class BollingerSqueezeStrategy(BaseStrategy):
    METADATA = StrategyMetadata(strategy_id="BB_SQUEEZE_H1_V1",name="Bollinger Squeeze Breakout H1",version="1.0.0",
        description="Trades the breakout from a Bollinger Band squeeze.",instruments=ALL_INSTRUMENTS,timeframes=["H1"],min_history_bars=220)
    def __init__(self,pip_size=0.0001,sl_atr=1.5,tp_atr=2.5,sq=20):
        super().__init__(); self.pip_size=pip_size; self.sl_atr=sl_atr; self.tp_atr=tp_atr; self.sq=sq
    def generate_signal(self,data,instrument,timeframe,current_bar_index=-1):
        if not self.validate_data(data): return None
        bt=data.index[-1]; ins,il=_in_session(bt)
        if not ins or not _no_fri(bt): return None
        c=data["Close"]; h=data["High"]; l=data["Low"]
        bu,bm,bl=bollinger_bands(c,20,2.0); a=atr(h,l,c,14); e200=ema(c,200)
        ca=_f(a.iloc[-1]); ce200=_f(e200.iloc[-1])
        if not ca or ca<=0 or not ce200: return None
        bw=bu-bl
        if len(bw)<self.sq+2: return None
        cw=_f(bw.iloc[-1]); pw=_f(bw.iloc[-2])
        if cw is None or pw is None: return None
        mw=float(bw.iloc[-self.sq:-1].min())
        if not (pw<=mw*1.05 and cw>pw*1.1): return None
        cc=float(c.iloc[-1]); cu=_f(bu.iloc[-1]); clw=_f(bl.iloc[-1])
        if not cu or not clw: return None
        d=None
        if cc>cu and cc>ce200: d="BUY"
        elif cc<clw and cc<ce200: d="SELL"
        if not d: return None
        e=cc; sl=e-ca*self.sl_atr if d=="BUY" else e+ca*self.sl_atr
        tp=e+ca*self.tp_atr if d=="BUY" else e-ca*self.tp_atr
        return _sig(self.METADATA.strategy_id,instrument,d,e,sl,tp,timeframe,bt,0.70,{"band_width":round(cw,5),"session":"london" if il else "ny"})

class RSIMeanReversionStrategy(BaseStrategy):
    METADATA = StrategyMetadata(strategy_id="RSI_MEAN_REVERSION_H1_V1",name="RSI Mean Reversion H1",version="1.0.0",
        description="Fades extreme RSI readings. High win rate in ranging markets.",instruments=ALL_INSTRUMENTS,timeframes=["H1"],min_history_bars=220)
    def __init__(self,pip_size=0.0001,sl_atr=1.2,tp_atr=1.8,os=28,ob=72):
        super().__init__(); self.pip_size=pip_size; self.sl_atr=sl_atr; self.tp_atr=tp_atr; self.os=os; self.ob=ob
    def generate_signal(self,data,instrument,timeframe,current_bar_index=-1):
        if not self.validate_data(data): return None
        bt=data.index[-1]; ins,il=_in_session(bt)
        if not ins or not _no_fri(bt): return None
        c=data["Close"]; h=data["High"]; l=data["Low"]
        rs=rsi(c,14); a=atr(h,l,c,14); e50=ema(c,50); e200=ema(c,200)
        if len(rs)<3: return None
        cr=_f(rs.iloc[-1]); pr=_f(rs.iloc[-2]); ca=_f(a.iloc[-1])
        ce50=_f(e50.iloc[-1]); ce200=_f(e200.iloc[-1])
        if any(x is None for x in [cr,pr,ca,ce50,ce200]) or ca<=0: return None
        cc=float(c.iloc[-1]); bull=ce50>ce200; bear=ce50<ce200
        d=None
        if cr>self.os and pr<=self.os and bull: d="BUY"
        elif cr<self.ob and pr>=self.ob and bear: d="SELL"
        if not d: return None
        e=cc; sl=e-ca*self.sl_atr if d=="BUY" else e+ca*self.sl_atr
        tp=e+ca*self.tp_atr if d=="BUY" else e-ca*self.tp_atr
        if abs(tp-e)/abs(sl-e)<1.3: return None
        return _sig(self.METADATA.strategy_id,instrument,d,e,sl,tp,timeframe,bt,0.68,{"rsi":round(cr,1),"session":"london" if il else "ny"})

class DoubleTopBottomStrategy(BaseStrategy):
    METADATA = StrategyMetadata(strategy_id="DOUBLE_TOP_BOTTOM_H1_V1",name="Double Top/Bottom H1",version="1.0.0",
        description="Detects double top/bottom patterns and trades the neckline break.",instruments=ALL_INSTRUMENTS,timeframes=["H1"],min_history_bars=220)
    def __init__(self,pip_size=0.0001,sl_atr=1.5,tp_atr=2.5,lb=30,tol=0.5):
        super().__init__(); self.pip_size=pip_size; self.sl_atr=sl_atr; self.tp_atr=tp_atr; self.lb=lb; self.tol=tol
    def generate_signal(self,data,instrument,timeframe,current_bar_index=-1):
        if not self.validate_data(data): return None
        bt=data.index[-1]; ins,il=_in_session(bt)
        if not ins or not _no_fri(bt): return None
        c=data["Close"]; h=data["High"]; l=data["Low"]
        a=atr(h,l,c,14); e200=ema(c,200)
        ca=_f(a.iloc[-1]); ce200=_f(e200.iloc[-1])
        if not ca or ca<=0 or not ce200: return None
        tol=ca*self.tol; lb=min(self.lb,len(data)-5)
        rh=h.iloc[-lb:]; rl=l.iloc[-lb:]; rc=c.iloc[-lb:]
        cc=float(c.iloc[-1])
        if cc<ce200:
            p1i=rh.iloc[:-5].idxmax(); p1v=float(rh[p1i])
            ap=rh.loc[p1i:].iloc[3:]
            if len(ap)>=3:
                p2v=float(ap.max())
                if abs(p2v-p1v)<=tol:
                    neck=float(rc.loc[p1i:].min())
                    if neck-ca*2<cc<neck:
                        e=cc; sl=e+ca*self.sl_atr; tp=e-ca*self.tp_atr
                        if abs(tp-e)/abs(sl-e)<1.5: return None
                        return _sig(self.METADATA.strategy_id,instrument,"SELL",e,sl,tp,timeframe,bt,0.72,{"pattern":"double_top","neckline":round(neck,5)})
        if cc>ce200:
            t1i=rl.iloc[:-5].idxmin(); t1v=float(rl[t1i])
            at=rl.loc[t1i:].iloc[3:]
            if len(at)>=3:
                t2v=float(at.min())
                if abs(t2v-t1v)<=tol:
                    neck=float(rc.loc[t1i:].max())
                    if neck<cc<neck+ca*2:
                        e=cc; sl=e-ca*self.sl_atr; tp=e+ca*self.tp_atr
                        if abs(tp-e)/abs(sl-e)<1.5: return None
                        return _sig(self.METADATA.strategy_id,instrument,"BUY",e,sl,tp,timeframe,bt,0.72,{"pattern":"double_bottom","neckline":round(neck,5)})
        return None

class SupportResistanceBreakoutStrategy(BaseStrategy):
    METADATA = StrategyMetadata(strategy_id="SR_BREAKOUT_H1_V1",name="S/R Breakout H1",version="1.0.0",
        description="Trades decisive breaks through key support/resistance levels.",instruments=ALL_INSTRUMENTS,timeframes=["H1"],min_history_bars=220)
    def __init__(self,pip_size=0.0001,sl_atr=1.5,tp_atr=2.5,lb=20):
        super().__init__(); self.pip_size=pip_size; self.sl_atr=sl_atr; self.tp_atr=tp_atr; self.lb=lb
    def generate_signal(self,data,instrument,timeframe,current_bar_index=-1):
        if not self.validate_data(data): return None
        bt=data.index[-1]; ins,il=_in_session(bt)
        if not ins or not _no_fri(bt): return None
        c=data["Close"]; h=data["High"]; l=data["Low"]
        a=atr(h,l,c,14); e200=ema(c,200)
        ca=_f(a.iloc[-1]); ce200=_f(e200.iloc[-1])
        if not ca or ca<=0 or not ce200: return None
        lb=min(self.lb,len(data)-3)
        res=float(h.iloc[-lb-1:-1].max()); sup=float(l.iloc[-lb-1:-1].min())
        cc=float(c.iloc[-1]); pc=float(c.iloc[-2])
        d=None
        if pc<=res and cc>res+ca*0.3 and cc>ce200: d="BUY"
        elif pc>=sup and cc<sup-ca*0.3 and cc<ce200: d="SELL"
        if not d: return None
        e=cc; sl=e-ca*self.sl_atr if d=="BUY" else e+ca*self.sl_atr
        tp=e+ca*self.tp_atr if d=="BUY" else e-ca*self.tp_atr
        return _sig(self.METADATA.strategy_id,instrument,d,e,sl,tp,timeframe,bt,0.67,{"resistance":round(res,5),"support":round(sup,5),"session":"london" if il else "ny"})

class LondonOpenBreakoutStrategy(BaseStrategy):
    METADATA = StrategyMetadata(strategy_id="LONDON_OPEN_H1_V1",name="London Open Breakout H1",version="1.0.0",
        description="Trades the London open breakout of the Asian session range.",
        instruments=["EUR_USD","GBP_USD","USD_JPY","EUR_GBP","EUR_JPY","GBP_JPY","XAU_USD"],timeframes=["H1"],min_history_bars=220)
    def __init__(self,pip_size=0.0001,sl_atr=1.5,tp_atr=2.0,lo=7,ab=7):
        super().__init__(); self.pip_size=pip_size; self.sl_atr=sl_atr; self.tp_atr=tp_atr; self.lo=lo; self.ab=ab
    def generate_signal(self,data,instrument,timeframe,current_bar_index=-1):
        if not self.validate_data(data): return None
        bt=data.index[-1]
        if not hasattr(bt,"hour") or bt.hour!=self.lo or not _no_fri(bt): return None
        c=data["Close"]; h=data["High"]; l=data["Low"]
        a=atr(h,l,c,14); e200=ema(c,200)
        ca=_f(a.iloc[-1]); ce200=_f(e200.iloc[-1])
        if not ca or ca<=0 or not ce200: return None
        lb=min(self.ab,len(data)-2)
        ah=float(h.iloc[-lb-1:-1].max()); al=float(l.iloc[-lb-1:-1].min())
        rs=ah-al
        if rs<ca*0.3 or rs>ca*4.0: return None
        cc=float(c.iloc[-1]); d=None
        if cc>ah and cc>ce200: d="BUY"
        elif cc<al and cc<ce200: d="SELL"
        if not d: return None
        e=cc; sl=al-ca*0.3 if d=="BUY" else ah+ca*0.3
        tp=e+(e-sl)*self.tp_atr if d=="BUY" else e-(sl-e)*self.tp_atr
        if abs(tp-e)/abs(sl-e)<1.5: return None
        return _sig(self.METADATA.strategy_id,instrument,d,e,sl,tp,timeframe,bt,0.70,{"asian_high":round(ah,5),"asian_low":round(al,5),"range_pips":round(rs/self.pip_size,1)})
