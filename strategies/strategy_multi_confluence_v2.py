from __future__ import annotations
import math
from datetime import datetime
from typing import Optional
import pandas as pd
from indicators.technical import atr, bollinger_bands, ema, rsi
from logs.logger import get_logger
from strategies.base import BaseStrategy, StrategyMetadata, TradeSignal
log = get_logger(__name__)

ALL_INSTRUMENTS = [
    "EUR_USD","GBP_USD","USD_JPY","USD_CHF","AUD_USD","USD_CAD","NZD_USD",
    "EUR_GBP","EUR_JPY","EUR_CHF","EUR_AUD","EUR_CAD","GBP_JPY","GBP_CHF",
    "GBP_AUD","GBP_CAD","AUD_JPY","AUD_CAD","AUD_CHF","AUD_NZD","CAD_JPY",
    "CHF_JPY","NZD_JPY","NZD_USD","XAU_USD","XAG_USD",
]

def _safe(v):
    try: x=float(v); return None if math.isnan(x) or math.isinf(x) else x
    except: return None

def calc_adx(high, low, close, period=14):
    if len(high)<period*2: return 0.0
    try:
        tr_l,dmp_l,dmm_l=[],[],[]
        for i in range(1,len(high)):
            hl=float(high.iloc[i])-float(low.iloc[i])
            hc=abs(float(high.iloc[i])-float(close.iloc[i-1]))
            lc=abs(float(low.iloc[i])-float(close.iloc[i-1]))
            tr_l.append(max(hl,hc,lc))
            up=float(high.iloc[i])-float(high.iloc[i-1])
            dn=float(low.iloc[i-1])-float(low.iloc[i])
            dmp_l.append(up if up>dn and up>0 else 0)
            dmm_l.append(dn if dn>up and dn>0 else 0)
        tr=pd.Series(tr_l); dmp=pd.Series(dmp_l); dmm=pd.Series(dmm_l)
        as_=tr.ewm(span=period,adjust=False).mean()
        dip=(dmp.ewm(span=period,adjust=False).mean()/as_.replace(0,0.0001))*100
        dim=(dmm.ewm(span=period,adjust=False).mean()/as_.replace(0,0.0001))*100
        dx=(abs(dip-dim)/(dip+dim).replace(0,0.0001))*100
        adx=dx.ewm(span=period,adjust=False).mean()
        v=_safe(adx.iloc[-1]); return v if v is not None else 0.0
    except: return 0.0

class MultiConfluenceV2Strategy(BaseStrategy):
    METADATA = StrategyMetadata(
        strategy_id="MULTI_CONFLUENCE_V2",
        name="Multi-Confluence v2 All Pairs",
        version="2.0.0",
        description="6-condition confluence strategy targeting 60%+ win rate across all 26 pairs.",
        instruments=ALL_INSTRUMENTS,
        timeframes=["M15"],
        min_history_bars=50,
    )
    EMA_FAST=9; EMA_MID=21; EMA_TREND=50; EMA_HTF=100
    RSI_PERIOD=14; RSI_BUY_LOW=48; RSI_BUY_HIGH=68
    RSI_SELL_LOW=32; RSI_SELL_HIGH=52
    ATR_PERIOD=14; ATR_EXPAND_LOOKBACK=5
    ADX_MIN=25; MIN_RR=3.0; SWING_LOOKBACK=10; SL_BUFFER_PIPS=3
    LONDON_START=7; LONDON_END=12; NY_START=13; NY_END=18

    def __init__(self, pip_size=0.0001):
        super().__init__(); self.pip_size=pip_size

    def generate_signal(self, data, instrument, timeframe, current_bar_index=-1):
        if not self.validate_data(data): return None
        if len(data)<self.METADATA.min_history_bars: return None
        close=data["Close"]; high=data["High"]; low=data["Low"]
        bar_time=data.index[-1]
        # Parse time from string or datetime
        try:
            if isinstance(bar_time, str):
                from datetime import datetime as dt
                bar_dt = dt.strptime(bar_time[:19], "%Y-%m-%dT%H:%M:%S")
            elif hasattr(bar_time, "hour"):
                bar_dt = bar_time
            else:
                bar_dt = bar_time.to_pydatetime()
            h = bar_dt.hour
            if not(self.LONDON_START<=h<self.LONDON_END or self.NY_START<=h<self.NY_END): return None
            if bar_dt.weekday()==4 and h>=15: return None
        except Exception:
            pass  # If time parsing fails, allow the signal
        e9=ema(close,self.EMA_FAST); e21=ema(close,self.EMA_MID)
        e50=ema(close,self.EMA_TREND); e200=ema(close,self.EMA_HTF)
        rsi_s=rsi(close,self.RSI_PERIOD)
        bb_upper,bb_mid,bb_lower=bollinger_bands(close,20,2.0)
        atr_s=atr(high,low,close,self.ATR_PERIOD)
        ce9=_safe(e9.iloc[-1]); ce21=_safe(e21.iloc[-1])
        ce50=_safe(e50.iloc[-1]); ce200=_safe(e200.iloc[-1])
        crsi=_safe(rsi_s.iloc[-1]); catr=_safe(atr_s.iloc[-1])
        cclose=_safe(close.iloc[-1]); cbb_mid=_safe(bb_mid.iloc[-1])
        if any(v is None for v in [ce9,ce21,ce50,ce200,crsi,catr,cclose,cbb_mid]): return None
        if len(atr_s)<self.ATR_EXPAND_LOOKBACK+1: return None
        avg_atr=float(atr_s.iloc[-(self.ATR_EXPAND_LOOKBACK+1):-1].mean())
        atr_exp=catr>avg_atr*1.05
        adx=calc_adx(high,low,close,14)
        if adx<self.ADX_MIN: return None
        buy_c=[ce9>ce21, ce21>ce50, ce50>ce200, cclose>cbb_mid,
               self.RSI_BUY_LOW<=crsi<=self.RSI_BUY_HIGH]
        sell_c=[ce9<ce21, ce21<ce50, ce50<ce200, cclose<cbb_mid,
                self.RSI_SELL_LOW<=crsi<=self.RSI_SELL_HIGH]
        bs=sum(buy_c); ss=sum(sell_c)
        # Require 4 of 5 conditions
        if bs<4 and ss<4: return None
        direction="BUY" if bs>=5 else "SELL"
        direction="BUY" if bs==6 else "SELL"
        entry=cclose; buf=self.SL_BUFFER_PIPS*self.pip_size
        if direction=="BUY":
            sl=float(low.iloc[-self.SWING_LOOKBACK:].min())-buf
        else:
            sl=float(high.iloc[-self.SWING_LOOKBACK:].max())+buf
        sl_dist=abs(entry-sl)
        if sl_dist<self.pip_size*5:
            sl_dist=catr*1.5
            sl=entry-sl_dist if direction=="BUY" else entry+sl_dist
        if sl_dist<=0: return None
        tp_dist=sl_dist*self.MIN_RR
        tp=entry+tp_dist if direction=="BUY" else entry-tp_dist
        conf=min(0.60+min(adx-self.ADX_MIN,20)/100, 0.92)
        return TradeSignal(
            strategy_id=self.METADATA.strategy_id, instrument=instrument,
            direction=direction, entry_price=round(entry,5),
            stop_loss=round(sl,5), take_profit=round(tp,5),
            confidence=round(conf,2), timeframe=timeframe,
            timestamp=bar_time if isinstance(bar_time,datetime) else datetime.utcnow(),
            metadata={"adx":round(adx,1),"rsi":round(crsi,1),"atr_expanding":atr_exp}
        )
