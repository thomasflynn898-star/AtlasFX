from __future__ import annotations
import math
from datetime import datetime
from typing import Optional
from logs.logger import get_logger
log = get_logger(__name__)

def _safe(v):
    try: x=float(v); return None if math.isnan(x) or math.isinf(x) else x
    except: return None

class TradeManager:
    BREAKEVEN_R=1.0; TRAIL_START_R=1.5; TRAIL_TIGHT_R=2.0
    TRAIL_DISTANCE_ATR=1.0; TRAIL_TIGHT_ATR=0.5

    def __init__(self, broker):
        self._broker=broker
        self._invalidation_counts={}

    def evaluate(self, trade_id, position):
        result={"close":False,"close_reason":None,"modify_sl":False,"new_sl":None,"action":"hold"}
        instrument=position.get("instrument"); direction=position.get("direction")
        entry=position.get("entry_price",0); original_sl=position.get("stop_loss",0)
        tp=position.get("take_profit",0); pip_size=position.get("pip_size",0.0001)
        current_sl=position.get("current_sl",original_sl)
        try:
            price=self._broker.get_price(instrument); current=price.mid
        except Exception as e:
            log.error("trade_manager_price_failed",instrument=instrument,error=str(e)); return result
        risk_distance=abs(entry-original_sl)
        if risk_distance<=0: return result
        profit_distance=(current-entry) if direction=="BUY" else (entry-current)
        profit_r=profit_distance/risk_distance
        if self._check_invalidation(trade_id,instrument,direction):
            result["close"]=True; result["close_reason"]="invalidation_h4_flip"
            result["action"]="close H4 flipped"
            log.info("trade_invalidated",trade_id=trade_id,instrument=instrument,profit_r=round(profit_r,2))
            return result
        try:
            h1=self._broker.get_candles_as_dataframe(instrument,"H1",50)
            if h1 is not None and len(h1)>15:
                from indicators.technical import atr as calc_atr
                a=calc_atr(h1["High"],h1["Low"],h1["Close"],14)
                current_atr=_safe(a.iloc[-1]) or risk_distance
            else: current_atr=risk_distance
        except: current_atr=risk_distance
        new_sl=None
        if profit_r>=self.TRAIL_TIGHT_R:
            trail_dist=current_atr*self.TRAIL_TIGHT_ATR
            if direction=="BUY":
                c=current-trail_dist
                if c>current_sl: new_sl=c
            else:
                c=current+trail_dist
                if c<current_sl: new_sl=c
        elif profit_r>=self.TRAIL_START_R:
            trail_dist=current_atr*self.TRAIL_DISTANCE_ATR
            if direction=="BUY":
                c=current-trail_dist
                if c>current_sl: new_sl=c
            else:
                c=current+trail_dist
                if c<current_sl: new_sl=c
        elif profit_r>=self.BREAKEVEN_R:
            buf=pip_size*2
            if direction=="BUY":
                c=entry+buf
                if c>current_sl: new_sl=c
            else:
                c=entry-buf
                if c<current_sl: new_sl=c
        if new_sl is not None:
            result["modify_sl"]=True; result["new_sl"]=round(new_sl,5)
            result["action"]=f"trail_sl to {round(new_sl,5)} profit={round(profit_r,2)}R"
            log.info("trailing_stop_updated",trade_id=trade_id,instrument=instrument,
                     old_sl=round(current_sl,5),new_sl=round(new_sl,5),profit_r=round(profit_r,2))
        return result

    def _check_invalidation(self, trade_id, instrument, direction):
        try:
            h4=self._broker.get_candles_as_dataframe(instrument,"H4",250)
            if h4 is None or len(h4)<201: return False
            from strategies.mtf_engine import get_h4_bias
            bias=get_h4_bias(h4)
            against=(direction=="BUY" and bias=="BEAR") or (direction=="SELL" and bias=="BULL")
            if against:
                self._invalidation_counts[trade_id]=self._invalidation_counts.get(trade_id,0)+1
                return self._invalidation_counts[trade_id]>=2
            else:
                self._invalidation_counts[trade_id]=0; return False
        except Exception as e:
            log.error("invalidation_check_failed",trade_id=trade_id,error=str(e)); return False
