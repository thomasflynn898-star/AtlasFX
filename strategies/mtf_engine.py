from __future__ import annotations
import math
from datetime import datetime
from typing import Optional
import pandas as pd
from indicators.technical import atr, ema, rsi
from logs.logger import get_logger
from strategies.base import BaseStrategy, TradeSignal
log = get_logger(__name__)

def _safe(v):
    try: x=float(v); return None if math.isnan(x) or math.isinf(x) else x
    except: return None

def get_h4_bias(data):
    if data is None or len(data)<201: return "NEUTRAL"
    c=data["Close"]; h=data["High"]; l=data["Low"]
    e50=ema(c,50); e200=ema(c,200); a=atr(h,l,c,14)
    ce50=_safe(e50.iloc[-1]); ce200=_safe(e200.iloc[-1])
    catr=_safe(a.iloc[-1]); cc=_safe(c.iloc[-1])
    if any(v is None for v in [ce50,ce200,catr,cc]): return "NEUTRAL"
    if abs(cc-ce200)<catr*0.5: return "NEUTRAL"
    if ce50>ce200 and cc>ce200: return "BULL"
    if ce50<ce200 and cc<ce200: return "BEAR"
    return "NEUTRAL"

def get_h1_trend(data):
    if data is None or len(data)<52: return "NEUTRAL"
    c=data["Close"]; e50=ema(c,50); rs=rsi(c,14)
    ce50=_safe(e50.iloc[-1]); cr=_safe(rs.iloc[-1]); cc=_safe(c.iloc[-1])
    if any(v is None for v in [ce50,cr,cc]): return "NEUTRAL"
    if cc>ce50 and cr>52: return "BULL"
    if cc<ce50 and cr<48: return "BEAR"
    return "NEUTRAL"

def bias_matches_signal(h4, h1, direction):
    if h4=="NEUTRAL" or h1=="NEUTRAL": return False
    if direction=="BUY": return h4=="BULL" and h1=="BULL"
    if direction=="SELL": return h4=="BEAR" and h1=="BEAR"
    return False

class MTFEngine:
    H4_CANDLES=300; H1_CANDLES=300; M15_CANDLES=300
    def __init__(self, broker): self._broker=broker

    def evaluate(self, instrument, strategy, pip_size=0.0001):
        try: h4=self._broker.get_candles_as_dataframe(instrument,"H4",self.H4_CANDLES)
        except Exception as e: log.error("mtf_h4_failed",instrument=instrument,error=str(e)); return None
        h4b=get_h4_bias(h4)
        if h4b=="NEUTRAL": return None
        try: h1=self._broker.get_candles_as_dataframe(instrument,"H1",self.H1_CANDLES)
        except Exception as e: log.error("mtf_h1_failed",instrument=instrument,error=str(e)); return None
        h1t=get_h1_trend(h1)
        if h1t=="NEUTRAL" or h4b!=h1t: return None
        try: m15=self._broker.get_candles_as_dataframe(instrument,"M15",self.M15_CANDLES)
        except Exception as e: log.error("mtf_m15_failed",instrument=instrument,error=str(e)); return None
        if m15 is None or len(m15)<strategy.METADATA.min_history_bars: return None
        signal=strategy.generate_signal(data=m15,instrument=instrument,timeframe="M15")
        if signal is None: return None
        if not bias_matches_signal(h4b,h1t,signal.direction): return None
        # Stop upgrade disabled - causes position sizing issues
        pass
        log.info("mtf_confirmed",instrument=instrument,direction=signal.direction,
                 strategy=strategy.METADATA.strategy_id,h4=h4b,h1=h1t,
                 entry=signal.entry_price,rr=round(signal.risk_reward_ratio,2))
        signal.metadata=signal.metadata or {}
        signal.metadata.update({"mtf_confirmed":True,"h4_bias":h4b,"h1_trend":h1t,"entry_tf":"M15"})
        return signal

    def _upgrade_stops(self, signal, h1, pip_size):
        a=atr(h1["High"],h1["Low"],h1["Close"],14)
        h1atr=_safe(a.iloc[-1])
        if not h1atr or h1atr<=0: return signal
        e=signal.entry_price
        sl_m15=abs(e-signal.stop_loss); tp_m15=abs(signal.take_profit-e)
        sl=max(sl_m15,h1atr*1.5); tp=max(tp_m15,h1atr*2.5)
        if tp/sl<2.0: tp=sl*2.5
        nsl=e-sl if signal.direction=="BUY" else e+sl
        ntp=e+tp if signal.direction=="BUY" else e-tp
        from dataclasses import replace
        return replace(signal,stop_loss=round(nsl,5),take_profit=round(ntp,5))

    def get_market_context(self, instrument):
        try:
            h4=self._broker.get_candles_as_dataframe(instrument,"H4",300)
            h1=self._broker.get_candles_as_dataframe(instrument,"H1",300)
            h4b=get_h4_bias(h4); h1t=get_h1_trend(h1)
            aligned=h4b==h1t and h4b!="NEUTRAL"
            return {"instrument":instrument,"h4_bias":h4b,"h1_trend":h1t,"aligned":aligned,"tradeable":aligned}
        except Exception as e:
            return {"instrument":instrument,"error":str(e)}
