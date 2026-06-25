from __future__ import annotations
import math
import pandas as pd
from indicators.technical import atr, bollinger_bands, ema
from logs.logger import get_logger
log = get_logger(__name__)

TRENDING_STRATEGIES = ["MULTI_CONFLUENCE_H1_V1","EMA_CROSSOVER_H1_V1","SR_BREAKOUT_H1_V1","LONDON_OPEN_H1_V1"]
RANGING_STRATEGIES = ["RSI_MEAN_REVERSION_H1_V1","DOUBLE_TOP_BOTTOM_H1_V1","BB_SQUEEZE_H1_V1"]
VOLATILE_STRATEGIES = ["BB_SQUEEZE_H1_V1","SR_BREAKOUT_H1_V1","LONDON_OPEN_H1_V1","EMA_CROSSOVER_H1_V1"]
ALL_STRATEGIES = list(set(TRENDING_STRATEGIES+RANGING_STRATEGIES+VOLATILE_STRATEGIES))

def _safe(v):
    try: x=float(v); return None if math.isnan(x) or math.isinf(x) else x
    except: return None

def calculate_adx(high, low, close, period=14):
    if len(high)<period*2: return 0.0
    try:
        tr_list,dmp_list,dmm_list=[],[],[]
        for i in range(1,len(high)):
            hl=float(high.iloc[i])-float(low.iloc[i])
            hc=abs(float(high.iloc[i])-float(close.iloc[i-1]))
            lc=abs(float(low.iloc[i])-float(close.iloc[i-1]))
            tr_list.append(max(hl,hc,lc))
            up=float(high.iloc[i])-float(high.iloc[i-1])
            down=float(low.iloc[i-1])-float(low.iloc[i])
            dmp_list.append(up if up>down and up>0 else 0)
            dmm_list.append(down if down>up and down>0 else 0)
        tr=pd.Series(tr_list); dmp=pd.Series(dmp_list); dmm=pd.Series(dmm_list)
        atr_s=tr.ewm(span=period,adjust=False).mean()
        dip=(dmp.ewm(span=period,adjust=False).mean()/atr_s.replace(0,0.0001))*100
        dim=(dmm.ewm(span=period,adjust=False).mean()/atr_s.replace(0,0.0001))*100
        dx=(abs(dip-dim)/(dip+dim).replace(0,0.0001))*100
        adx=dx.ewm(span=period,adjust=False).mean()
        v=_safe(adx.iloc[-1]); return v if v is not None else 0.0
    except Exception as e:
        log.debug("adx_failed",error=str(e)); return 0.0

class RegimeDetector:
    ADX_TREND=25.0; ADX_RANGE=20.0; ATR_VOLATILE=1.5; ATR_LB=20

    def detect(self, data):
        if data is None or len(data)<50: return "UNKNOWN"
        h=data["High"]; l=data["Low"]; c=data["Close"]
        try:
            adx=calculate_adx(h,l,c,14)
            atr_s=atr(h,l,c,14)
            catr=_safe(atr_s.iloc[-1]); aatr=_safe(atr_s.iloc[-self.ATR_LB:].mean())
            atr_ratio=catr/aatr if catr and aatr and aatr>0 else 1.0
            bu,bm,bl=bollinger_bands(c,20,2.0); bw=bu-bl
            cw=_safe(bw.iloc[-1]); aw=_safe(bw.iloc[-self.ATR_LB:].mean())
            squeeze=cw is not None and aw is not None and aw>0 and cw<aw*0.7
            e50=ema(c,50); e200=ema(c,200)
            ce200=_safe(e200.iloc[-1]); cc=_safe(c.iloc[-1])
            if atr_ratio>self.ATR_VOLATILE or squeeze: regime="VOLATILE"
            elif adx>=self.ADX_TREND:
                regime="TRENDING_BULL" if (cc and ce200 and cc>ce200) else "TRENDING_BEAR"
            elif adx<self.ADX_RANGE: regime="RANGING"
            else: regime="UNKNOWN"
            log.debug("regime_detected",regime=regime,adx=round(adx,1),atr_ratio=round(atr_ratio,2))
            return regime
        except Exception as e:
            log.error("regime_failed",error=str(e)); return "UNKNOWN"

    def get_allowed_strategies(self, regime):
        if regime in ("TRENDING_BULL","TRENDING_BEAR"): return TRENDING_STRATEGIES
        elif regime=="RANGING": return RANGING_STRATEGIES
        elif regime=="VOLATILE": return VOLATILE_STRATEGIES
        return list(set(ALL_STRATEGIES))

    def is_strategy_allowed(self, strategy_id, regime):
        return strategy_id in self.get_allowed_strategies(regime)

    def get_regime_description(self, regime):
        return {"TRENDING_BULL":"Strong uptrend — trend strategies active",
                "TRENDING_BEAR":"Strong downtrend — trend strategies active",
                "RANGING":"Sideways — mean reversion active",
                "VOLATILE":"High volatility — breakout strategies active",
                "UNKNOWN":"Transitional — all strategies active"}.get(regime,"Unknown")
