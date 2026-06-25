from __future__ import annotations
from datetime import datetime
from typing import Optional
import pandas as pd
from indicators.technical import atr, bollinger_bands, ema, rsi
from logs.logger import get_logger
from strategies.base import BaseStrategy, StrategyMetadata, TradeSignal
log = get_logger(__name__)

class MultiConfluenceStrategy(BaseStrategy):
    METADATA = StrategyMetadata(
        strategy_id="MULTI_CONFLUENCE_H1_V1",
        name="Multi-Confluence H1 Day Trading",
        version="1.0.0",
        description="5-condition confluence H1 day trading strategy. EMA trend + RSI + Bollinger + session filter. NOT validated for live trading.",
        instruments=["EUR_USD","GBP_USD","USD_JPY","XAU_USD"],
        timeframes=["H1"],
        min_history_bars=220,
    )
    def __init__(self, ema_fast=9, ema_mid=21, ema_trend=50, ema_htf=200,
                 rsi_period=14, rsi_low=40.0, rsi_high=60.0,
                 bb_period=20, bb_std=2.0, atr_period=14,
                 sl_atr_mult=1.5, tp_atr_mult=2.5, pip_size=0.0001,
                 london_start=7, london_end=12, ny_start=13, ny_end=18):
        super().__init__()
        self.ema_fast=ema_fast; self.ema_mid=ema_mid; self.ema_trend=ema_trend
        self.ema_htf=ema_htf; self.rsi_period=rsi_period; self.rsi_low=rsi_low
        self.rsi_high=rsi_high; self.bb_period=bb_period; self.bb_std=bb_std
        self.atr_period=atr_period; self.sl_atr_mult=sl_atr_mult
        self.tp_atr_mult=tp_atr_mult; self.pip_size=pip_size
        self.london_start=london_start; self.london_end=london_end
        self.ny_start=ny_start; self.ny_end=ny_end

    def generate_signal(self, data, instrument, timeframe, current_bar_index=-1):
        if not self.validate_data(data): return None
        close=data["Close"]; high=data["High"]; low=data["Low"]
        bar_time=data.index[-1]
        in_london=False; in_ny=False
        if hasattr(bar_time,"hour"):
            hour=bar_time.hour
            in_london=self.london_start<=hour<self.london_end
            in_ny=self.ny_start<=hour<self.ny_end
            if not in_london and not in_ny: return None
        if hasattr(bar_time,"weekday"):
            if bar_time.weekday()==4 and hasattr(bar_time,"hour") and bar_time.hour>=15: return None
        ema9=ema(close,self.ema_fast); ema21=ema(close,self.ema_mid)
        ema50=ema(close,self.ema_trend); ema200=ema(close,self.ema_htf)
        rsi_s=rsi(close,self.rsi_period)
        bb_upper,bb_mid,bb_lower=bollinger_bands(close,self.bb_period,self.bb_std)
        atr_s=atr(high,low,close,self.atr_period)
        if len(ema9)<2: return None
        import math
        cur_close=float(close.iloc[-1]); cur_ema9=float(ema9.iloc[-1])
        cur_ema21=float(ema21.iloc[-1]); cur_ema50=float(ema50.iloc[-1])
        cur_ema200=float(ema200.iloc[-1]); cur_rsi=float(rsi_s.iloc[-1])
        cur_atr=float(atr_s.iloc[-1]); cur_bb_up=float(bb_upper.iloc[-1])
        cur_bb_lo=float(bb_lower.iloc[-1]); prev_ema9=float(ema9.iloc[-2])
        prev_ema21=float(ema21.iloc[-2])
        for v in [cur_ema9,cur_ema21,cur_ema50,cur_ema200,cur_rsi,cur_atr,cur_bb_up,cur_bb_lo]:
            if math.isnan(v): return None
        if cur_atr<=0: return None
        bull_trend=cur_ema50>cur_ema200; bear_trend=cur_ema50<cur_ema200
        if not bull_trend and not bear_trend: return None
        bull_cross=(prev_ema9<prev_ema21)and(cur_ema9>cur_ema21)
        bear_cross=(prev_ema9>prev_ema21)and(cur_ema9<cur_ema21)
        valid_bull=bull_trend and bull_cross; valid_bear=bear_trend and bear_cross
        if not valid_bull and not valid_bear: return None
        if valid_bull and cur_rsi>65: return None
        if valid_bear and cur_rsi<35: return None
        if valid_bull and cur_rsi<45: return None
        if valid_bear and cur_rsi>55: return None
        if cur_close>cur_bb_up or cur_close<cur_bb_lo: return None
        if abs(cur_close-cur_ema50)>cur_atr*2.0: return None
        direction="BUY" if valid_bull else "SELL"
        entry=cur_close; sl_dist=cur_atr*self.sl_atr_mult; tp_dist=cur_atr*self.tp_atr_mult
        stop_loss=entry-sl_dist if direction=="BUY" else entry+sl_dist
        take_profit=entry+tp_dist if direction=="BUY" else entry-tp_dist
        if tp_dist/sl_dist<1.5: return None
        score=0.5
        if tp_dist/sl_dist>=2.5: score+=0.1
        if 48<=cur_rsi<=56: score+=0.1
        if in_london: score+=0.05
        if abs(cur_close-cur_ema50)/cur_atr<0.5: score+=0.1
        confidence=round(min(max(score,0.0),1.0),2)
        try:
            return TradeSignal(
                strategy_id=self.METADATA.strategy_id,
                instrument=instrument, direction=direction,
                entry_price=round(entry,5), stop_loss=round(stop_loss,5),
                take_profit=round(take_profit,5), confidence=confidence,
                timeframe=timeframe,
                timestamp=bar_time if isinstance(bar_time,datetime) else datetime.utcnow(),
                metadata={"atr":round(cur_atr,5),"rsi":round(cur_rsi,1),
                         "ema50":round(cur_ema50,5),"rr":round(tp_dist/sl_dist,2),
                         "session":"london" if in_london else "ny"})
        except ValueError as e:
            log.debug("signal_invalid",error=str(e)); return None
