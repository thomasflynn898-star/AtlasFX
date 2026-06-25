"""
dashboard/app.py - AtlasFX Pro — Gold Edition
Designed around the AtlasFX brand identity: deep charcoal, gold accents, premium feel
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from analytics.performance import PerformanceAnalytics
from broker.oanda import OANDABroker
from config.settings import settings
from logs.logger import get_logger

log = get_logger(__name__)
app = FastAPI(title="AtlasFX Pro", docs_url=None, redoc_url=None)
analytics = PerformanceAnalytics()
_broker: Optional[OANDABroker] = None

# Auto-sync VPS database on startup
import subprocess, threading, time as _time, os

def _sync_db():
    while True:
        try:
            subprocess.run(
                ["scp", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
                 "-i", os.path.expanduser("~/.ssh/atlasfx_vps"),
                 "root@158.220.93.163:/opt/atlasfx/data/atlasfx.db",
                 os.path.expanduser("~/Desktop/AtlasFX/data/atlasfx.db")],
                capture_output=True, timeout=15)
        except Exception:
            pass
        _time.sleep(60)

threading.Thread(target=_sync_db, daemon=True, name="db-sync").start()

def get_broker():
    global _broker
    if _broker is None and settings.oanda_api_key:
        try:
            _broker = OANDABroker(api_key=settings.oanda_api_key,
                account_id=settings.oanda_account_id,
                environment=settings.oanda_environment.value)
        except Exception as e:
            log.error("dashboard_broker_init_failed", error=str(e))
    return _broker

@app.get("/api/sync")
def api_sync():
    import subprocess, os
    result=subprocess.run(
        ["scp","-o","ConnectTimeout=5","-o","BatchMode=yes",
         "-i",os.path.expanduser("~/.ssh/atlasfx_vps"),
         "root@158.220.93.163:/opt/atlasfx/data/atlasfx.db",
         os.path.expanduser("~/Desktop/AtlasFX/data/atlasfx.db")],
        capture_output=True,timeout=15)
    return {"success":result.returncode==0}

@app.get("/api/account")
def api_account():
    broker = get_broker()
    if not broker: return JSONResponse({"error":"Broker not configured"}, status_code=503)
    try:
        a = broker.get_account()
        return {"balance":a.balance,"nav":a.nav,"unrealised_pnl":a.unrealised_pnl,
                "currency":a.currency,"open_trade_count":a.open_trade_count}
    except Exception as e: return JSONResponse({"error":str(e)}, status_code=500)

@app.get("/api/prices")
def api_prices():
    broker = get_broker()
    if not broker: return JSONResponse({"error":"Broker not configured"}, status_code=503)
    instruments = ["EUR_USD","GBP_USD","USD_JPY","USD_CAD","NZD_USD","EUR_CAD",
                   "EUR_JPY","GBP_JPY","XAU_USD","AUD_USD","USD_CHF","EUR_GBP"]
    prices = {}
    try:
        # Fetch all in one OANDA request
        inst_str = "%2C".join(instruments)
        import requests as _req
        env = "practice" if "practice" in broker._environment else "live"
        url = f"https://api-fx{env}.oanda.com/v3/accounts/{broker._account_id}/pricing?instruments={inst_str}"
        r = _req.get(url, headers={"Authorization": f"Bearer {broker._api_key}"}, timeout=5)
        if r.status_code == 200:
            for price in r.json().get("prices", []):
                inst = price["instrument"]
                bid = float(price["bids"][0]["price"])
                ask = float(price["asks"][0]["price"])
                mid = round((bid+ask)/2, 6)
                pip = 0.01 if ("JPY" in inst or "XAU" in inst or "XAG" in inst) else 0.0001
                prices[inst] = {"bid":bid,"ask":ask,"mid":mid,"spread_pips":round((ask-bid)/pip,1)}
            return prices
    except Exception:
        pass
    # Fallback: individual calls
    for inst in instruments:
        try:
            p = broker.get_price(inst)
            pip = 0.01 if ("JPY" in inst or "XAU" in inst or "XAG" in inst) else 0.0001
            prices[inst] = {"bid":p.bid,"ask":p.ask,"mid":p.mid,"spread_pips":round(p.spread/pip,1)}
        except Exception as e:
            prices[inst] = {"error":str(e)}
    return prices

@app.get("/api/stats")
def api_stats(): return analytics.get_summary_stats()

@app.get("/api/trades/open")
def api_open_trades(): return analytics.get_open_trades()

@app.get("/api/trades/closed")
def api_closed_trades():
    trades = analytics.get_all_trades()
    # Filter out internal adjustment entries
    trades = [t for t in trades if t.get('instrument') != 'ADJUSTMENT']
    return trades[-100:]

@app.get("/api/equity")
def api_equity(): return analytics.get_equity_curve(initial_balance=100000.0)

@app.get("/api/by-instrument")
def api_by_instrument(): return analytics.get_trades_by_instrument()

@app.get("/api/by-strategy")
def api_by_strategy():
    trades = analytics.get_all_trades()
    trades = [t for t in trades if t.get("instrument") not in ["ADJUSTMENT","RECONCILIATION"]]
    result = {}
    for t in trades:
        s = (t.get("strategy_id") or "UNKNOWN").replace("_V1","").replace("_"," ")
        if s not in result:
            result[s] = {"trades":0,"wins":0,"losses":0,"pnl":0.0,"win_rate":0.0}
        result[s]["trades"] += 1
        pnl = t.get("pnl") or 0
        result[s]["pnl"] = round(result[s]["pnl"] + pnl, 2)
        if pnl >= 0: result[s]["wins"] += 1
        else: result[s]["losses"] += 1
    for s in result:
        t = result[s]["trades"]
        result[s]["win_rate"] = round(result[s]["wins"]/t*100, 1) if t else 0
    return result

@app.get("/api/weekly-pnl")
def api_weekly_pnl():
    from datetime import timedelta
    trades = analytics.get_all_trades()
    trades = [t for t in trades if t.get("instrument") not in ["ADJUSTMENT","RECONCILIATION"]
              and t.get("close_time") and t.get("pnl") is not None]
    weeks = {}
    for t in trades:
        try:
            dt = datetime.fromisoformat(str(t["close_time"]).replace("Z",""))
            # Get Monday of that week
            monday = (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d")
            if monday not in weeks:
                weeks[monday] = {"week":monday,"pnl":0.0,"trades":0,"wins":0}
            weeks[monday]["pnl"] = round(weeks[monday]["pnl"] + t["pnl"], 2)
            weeks[monday]["trades"] += 1
            if t["pnl"] >= 0: weeks[monday]["wins"] += 1
        except: pass
    return sorted(weeks.values(), key=lambda x: x["week"])

@app.get("/api/risk")
def api_risk():
    try:
        broker = get_broker()
        acct_data = {}
        if broker:
            try:
                a = broker.get_account()
                acct_data = {"balance":a.balance,"nav":a.nav,"unrealised_pnl":a.unrealised_pnl}
            except: pass
        return {"daily_dd_limit_pct":2.0,"weekly_dd_limit_pct":5.0,
                "risk_per_trade_pct":settings.risk_per_trade_pct,"max_exposure_pct":2.0,**acct_data}
    except Exception as e: return {"error":str(e)}

@app.get("/api/candles/{instrument}")
def api_candles(instrument: str, granularity: str = "M15", count: int = 100):
    broker = get_broker()
    if not broker: return JSONResponse({"error":"Broker not configured"}, status_code=503)
    try: return broker.get_candles(instrument, granularity, count)
    except Exception as e: return JSONResponse({"error":str(e)}, status_code=500)


import os as _os

@app.get("/", response_class=HTMLResponse)
def dashboard():
    html_file = _os.path.join(_os.path.dirname(__file__), "index.html")
    try:
        with open(html_file) as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        return HTMLResponse(content=f"<h1>Dashboard loading...</h1><p>{e}</p>")
