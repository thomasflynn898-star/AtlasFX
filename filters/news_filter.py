from __future__ import annotations
import json, time
from datetime import datetime, timedelta
from typing import Optional
import requests
from logs.logger import get_logger
log = get_logger(__name__)

CURRENCY_INSTRUMENTS = {
    "USD":["EUR_USD","GBP_USD","USD_JPY","USD_CHF","AUD_USD","USD_CAD","NZD_USD"],
    "EUR":["EUR_USD","EUR_JPY","EUR_CHF","EUR_AUD","EUR_CAD","EUR_GBP"],
    "GBP":["GBP_USD","GBP_JPY","GBP_CHF","GBP_AUD","GBP_CAD","EUR_GBP"],
    "JPY":["USD_JPY","EUR_JPY","GBP_JPY","AUD_JPY","CAD_JPY","CHF_JPY","NZD_JPY"],
    "AUD":["AUD_USD","AUD_JPY","AUD_CAD","AUD_CHF","AUD_NZD","GBP_AUD","EUR_AUD"],
    "CAD":["USD_CAD","EUR_CAD","GBP_CAD","AUD_CAD","CAD_JPY"],
    "CHF":["USD_CHF","EUR_CHF","GBP_CHF","AUD_CHF","CHF_JPY"],
    "NZD":["NZD_USD","NZD_JPY","AUD_NZD"],
    "XAU":["XAU_USD"],"XAG":["XAG_USD"],
}

HIGH_IMPACT_KEYWORDS = ["non-farm","nfp","payroll","cpi","inflation","interest rate",
    "rate decision","fed","fomc","boe","ecb","rba","rbnz","boc","gdp","unemployment",
    "jobless","pmi","powell","bailey","lagarde","ueda","macklem","retail sales",
    "trade balance","monetary policy"]

class NewsEvent:
    def __init__(self, currency, title, event_time, impact):
        self.currency=currency; self.title=title
        self.event_time=event_time; self.impact=impact
    def is_high_impact(self):
        t=self.title.lower()
        return self.impact=="high" or any(kw in t for kw in HIGH_IMPACT_KEYWORDS)
    def blackout_start(self, m=30): return self.event_time-timedelta(minutes=m)
    def blackout_end(self, m=30): return self.event_time+timedelta(minutes=m)

class NewsFilter:
    CACHE_TTL=6*3600; BB=30; BA=30
    def __init__(self):
        self._events=[]; self._last_fetch=0; self._failed=False
        log.info("news_filter_initialised", blackout_minutes=self.BB)

    def refresh(self):
        if time.time()-self._last_fetch<self.CACHE_TTL: return True
        try:
            r=requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                timeout=10,headers={"User-Agent":"AtlasFX/1.0"})
            if r.status_code!=200:
                self._failed=True; return False
            events=[]
            for item in r.json():
                try:
                    cur=item.get("country","").upper(); title=item.get("title","")
                    impact=item.get("impact","low").lower()
                    ds=item.get("date",""); ts=item.get("time","")
                    if not ds: continue
                    try:
                        dt=datetime.strptime(f"{ds} {ts}","%Y-%m-%d %I:%M%p") if ts else datetime.strptime(ds,"%Y-%m-%d")
                    except: continue
                    ev=NewsEvent(cur,title,dt,impact)
                    if ev.is_high_impact(): events.append(ev)
                except: continue
            self._events=events; self._last_fetch=time.time(); self._failed=False
            log.info("news_filter_refreshed",high_impact_events=len(events))
            return True
        except Exception as e:
            log.warning("news_filter_error",error=str(e)); self._failed=True; return False

    def is_safe_to_trade(self, instrument, check_time=None):
        self.refresh()
        if self._failed: return True, None
        now=check_time or datetime.utcnow()
        affected=[]
        for cur,insts in CURRENCY_INSTRUMENTS.items():
            if instrument in insts: affected.append(cur)
        if "XAU" in instrument: affected+= ["XAU","USD"]
        if "XAG" in instrument: affected+= ["XAG","USD"]
        for ev in self._events:
            if ev.currency not in affected: continue
            if ev.blackout_start(self.BB)<=now<=ev.blackout_end(self.BA):
                reason=f"News blackout: {ev.currency} {ev.title} at {ev.event_time.strftime("%H:%M UTC")}"
                log.info("news_filter_blocked",instrument=instrument,event=ev.title)
                return False, reason
        return True, None

    def get_upcoming_events(self, hours_ahead=4, check_time=None):
        self.refresh()
        now=check_time or datetime.utcnow(); cutoff=now+timedelta(hours=hours_ahead)
        return sorted([{"currency":ev.currency,"title":ev.title,
            "time":ev.event_time.strftime("%H:%M UTC"),"impact":ev.impact,
            "blackout_start":ev.blackout_start().strftime("%H:%M"),
            "blackout_end":ev.blackout_end().strftime("%H:%M")}
            for ev in self._events if now<=ev.event_time<=cutoff],key=lambda x:x["time"])
