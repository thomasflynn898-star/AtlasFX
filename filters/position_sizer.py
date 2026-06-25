from __future__ import annotations
from logs.logger import get_logger
from strategies.base import TradeSignal
log = get_logger(__name__)

HIGH_CONF=0.75; MED_CONF=0.60
HIGH_RISK=1.0; MED_RISK=0.5; LOW_RISK=0.25
MTF_BONUS=0.25; STREAK_PENALTY=0.25
MAX_RISK=1.5; MIN_RISK=0.10; MAX_EXPOSURE=3.0

class AdaptivePositionSizer:
    def calculate_risk_pct(self, signal, recent_trades=None,
                           current_dd_pct=0.0, daily_dd_limit_pct=2.0,
                           current_exposure_pct=0.0):
        conf = signal.confidence or 0.5
        if conf>=HIGH_CONF: risk=HIGH_RISK; tier="HIGH"
        elif conf>=MED_CONF: risk=MED_RISK; tier="MEDIUM"
        else: risk=LOW_RISK; tier="LOW"
        if (signal.metadata or {}).get("mtf_confirmed"): risk+=MTF_BONUS
        if recent_trades and self._consec_losses(recent_trades)>=3:
            risk-=STREAK_PENALTY
            log.info("sizer_streak_penalty", losses=self._consec_losses(recent_trades))
        if daily_dd_limit_pct>0:
            usage=current_dd_pct/daily_dd_limit_pct
            if usage>=0.8: risk*=0.5
            elif usage>=0.6: risk*=0.75
        remaining=MAX_EXPOSURE-current_exposure_pct
        if remaining<=0: return 0.0
        risk=min(risk,remaining)
        risk=round(max(MIN_RISK,min(MAX_RISK,risk)),2)
        log.info("position_sized", instrument=signal.instrument,
                 direction=signal.direction, confidence=conf,
                 tier=tier, mtf=(signal.metadata or {}).get("mtf_confirmed",False),
                 risk_pct=risk)
        return risk

    def _consec_losses(self, trades):
        count=0
        for t in reversed(trades):
            pnl=t.get("pnl",0) if isinstance(t,dict) else getattr(t,"pnl",0)
            if pnl is not None and pnl<0: count+=1
            else: break
        return count

    def get_size_summary(self, signal, account_balance):
        risk_pct=self.calculate_risk_pct(signal)
        risk_amt=account_balance*risk_pct/100
        return {"risk_pct":risk_pct,"risk_amount":round(risk_amt,2),
                "potential_profit":round(risk_amt*signal.risk_reward_ratio,2),
                "rr_ratio":round(signal.risk_reward_ratio,2),
                "confidence":signal.confidence}
