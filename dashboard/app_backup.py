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
    instruments = ["EUR_USD","GBP_USD","USD_JPY","USD_CHF","AUD_USD","USD_CAD",
                   "EUR_JPY","GBP_JPY","XAU_USD","XAG_USD","NZD_USD","EUR_GBP"]
    prices = {}
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
def api_closed_trades(): return analytics.get_all_trades()[-100:]

@app.get("/api/equity")
def api_equity(): return analytics.get_equity_curve(initial_balance=100000.0)

@app.get("/api/by-instrument")
def api_by_instrument(): return analytics.get_trades_by_instrument()

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


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>AtlasFX Pro</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;600;700&family=Inter:wght@300;400;500;600;700&family=Cinzel:wght@400;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --void: #080809;
  --deep: #0C0D0F;
  --surface: #111214;
  --raised: #181A1D;
  --card: #1C1E22;
  --border: #252729;
  --border2: #2E3035;
  --gold: #C9A84C;
  --gold2: #E8C96A;
  --gold3: #F5DFA0;
  --gold-dim: #8A6F2E;
  --gold-glow: rgba(201,168,76,0.15);
  --gold-line: linear-gradient(90deg, transparent, #C9A84C, #F5DFA0, #C9A84C, transparent);
  --text: #F0EDE8;
  --text2: #C8C4BC;
  --muted: #7A7670;
  --dim: #9A9690;
  --green: #22C97A;
  --green2: #3DD68C;
  --red: #FF4B4B;
  --red2: #FF6B6B;
  --blue: #4A9EFF;
  --purple: #9B6DFF;
  --mono: 'JetBrains Mono', monospace;
  --sans: 'Inter', sans-serif;
  --display: 'Cinzel', serif;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { font-size: 13px; }
body { background: var(--void); color: var(--text); font-family: var(--sans); min-height: 100vh; overflow-x: hidden; }

/* ── TICKER ── */
.ticker-wrap { background: var(--deep); border-bottom: 1px solid var(--border); overflow: hidden; height: 34px; display: flex; align-items: center; position: relative; }
.ticker-wrap::before,.ticker-wrap::after { content:''; position:absolute; top:0; bottom:0; width:80px; z-index:2; pointer-events:none; }
.ticker-wrap::before { left:0; background:linear-gradient(90deg,var(--deep),transparent); }
.ticker-wrap::after  { right:0; background:linear-gradient(-90deg,var(--deep),transparent); }
.ticker-track { display:flex; animation:ticker 50s linear infinite; white-space:nowrap; }
@keyframes ticker { 0%{transform:translateX(0)} 100%{transform:translateX(-50%)} }
.ticker-item { display:inline-flex; align-items:center; gap:10px; padding:0 28px; border-right:1px solid var(--border); font-family:var(--mono); font-size:11px; }
.ticker-pair { color:var(--muted); letter-spacing:.06em; text-transform:uppercase; }
.ticker-price { color:var(--text2); font-weight:500; transition:color .4s; }
.ticker-price.up   { color:var(--green); }
.ticker-price.down { color:var(--red); }
.ticker-dot { width:4px; height:4px; border-radius:50%; animation:blink 2.5s ease infinite; }
.ticker-dot.up   { background:var(--green); }
.ticker-dot.down { background:var(--red); }
@keyframes blink { 0%,100%{opacity:1}50%{opacity:.15} }

/* ── HEADER ── */
header { background:var(--deep); border-bottom:1px solid var(--border); padding:0 28px; height:60px; display:flex; align-items:center; justify-content:space-between; position:sticky; top:34px; z-index:100; }
header::after { content:''; position:absolute; bottom:0; left:0; right:0; height:1px; background:var(--gold-line); opacity:.4; }
.logo { display:flex; align-items:center; gap:14px; }
.logo-a { font-family:var(--display); font-size:22px; font-weight:700; background:linear-gradient(135deg,#C9A84C,#F5DFA0,#C9A84C); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; line-height:1; }
.logo-text-wrap { display:flex; flex-direction:column; }
.logo-name { font-family:var(--display); font-size:14px; font-weight:600; letter-spacing:.12em; background:linear-gradient(90deg,#C9A84C,#F5DFA0); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; }
.logo-tag { font-size:9px; letter-spacing:.18em; text-transform:uppercase; color:var(--muted); margin-top:1px; font-family:var(--sans); }
.header-divider { width:1px; height:24px; background:var(--border2); margin:0 4px; }
.nav-tab { padding:7px 16px; border-radius:6px; font-size:11px; font-weight:500; color:var(--muted); cursor:pointer; transition:all .2s; border:1px solid transparent; letter-spacing:.03em; }
.nav-tab:hover { color:var(--text2); background:var(--raised); }
.nav-tab.active { color:var(--gold); background:rgba(201,168,76,.08); border-color:rgba(201,168,76,.2); }
.header-right { display:flex; align-items:center; gap:18px; }
.live-badge { display:flex; align-items:center; gap:7px; padding:5px 12px; background:rgba(34,201,122,.08); border:1px solid rgba(34,201,122,.2); border-radius:20px; font-size:10px; font-weight:600; color:var(--green); letter-spacing:.1em; text-transform:uppercase; }
.live-dot { width:6px; height:6px; border-radius:50%; background:var(--green); animation:pulse 2s ease infinite; box-shadow:0 0 6px var(--green); }
@keyframes pulse { 0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(.8)} }
.clock { font-family:var(--mono); font-size:12px; color:var(--muted); letter-spacing:.06em; }
.refresh-btn { background:var(--raised); border:1px solid var(--border2); color:var(--muted); padding:7px 14px; border-radius:7px; cursor:pointer; font-size:11px; font-family:var(--sans); font-weight:500; transition:all .2s; display:flex; align-items:center; gap:7px; }
.refresh-btn:hover { color:var(--gold); border-color:rgba(201,168,76,.3); background:rgba(201,168,76,.05); }
.refresh-spin { display:inline-block; transition:transform .4s; }
.refresh-btn.loading .refresh-spin { animation:spin .6s linear infinite; }
@keyframes spin { to{transform:rotate(360deg)} }

/* ── SCAN INDICATOR ── */
.scan-ind { display:flex; align-items:center; gap:7px; font-size:10px; color:var(--muted); font-family:var(--mono); letter-spacing:.05em; }
.scan-ring { width:8px; height:8px; border-radius:50%; border:1.5px solid var(--border2); border-top-color:var(--gold); animation:spin 1.8s linear infinite; }

/* ── LAYOUT ── */
.main { padding:22px 28px; max-width:1640px; margin:0 auto; }
.view { display:none; }
.view.active { display:block; }

/* ── KPI ROW ── */
.kpi-row { display:grid; grid-template-columns:repeat(5,1fr); gap:1px; background:var(--border); border:1px solid var(--border); border-radius:12px; overflow:hidden; margin-bottom:20px; position:relative; }
.kpi { background:var(--surface); padding:18px 22px; position:relative; overflow:hidden; transition:background .2s; cursor:default; }
.kpi:hover { background:var(--raised); }
.kpi::after { content:''; position:absolute; top:0; left:0; right:0; height:1px; background:var(--gold-line); opacity:0; transition:opacity .3s; }
.kpi:hover::after { opacity:.6; }
.kpi-label { font-size:9px; font-weight:600; letter-spacing:.14em; text-transform:uppercase; color:var(--muted); margin-bottom:10px; }
.kpi-value { font-family:var(--mono); font-size:24px; font-weight:600; line-height:1; margin-bottom:5px; }
.kpi-value.gold { color:var(--gold); }
.kpi-sub { font-size:11px; color:var(--muted); }
.kpi-sub.pos { color:var(--green); }
.kpi-sub.neg { color:var(--red); }
.kpi-bg { position:absolute; right:14px; bottom:10px; font-size:36px; opacity:.04; }

/* ── GRID ── */
.g73 { display:grid; grid-template-columns:7fr 3fr; gap:16px; margin-bottom:16px; }
.g3  { display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-bottom:16px; }
.g2  { display:grid; grid-template-columns:repeat(2,1fr); gap:16px; margin-bottom:16px; }
.gap { margin-bottom:16px; }
@media(max-width:1200px) { .g73{grid-template-columns:1fr} .g3{grid-template-columns:repeat(2,1fr)} .kpi-row{grid-template-columns:repeat(3,1fr)} }
@media(max-width:768px)  { .g3,.g2{grid-template-columns:1fr} .kpi-row{grid-template-columns:repeat(2,1fr)} .main{padding:14px} }

/* ── PANEL ── */
.panel { background:var(--surface); border:1px solid var(--border); border-radius:10px; overflow:hidden; position:relative; }
.panel-header { display:flex; justify-content:space-between; align-items:center; padding:14px 18px; border-bottom:1px solid var(--border); position:relative; }
.panel-header::after { content:''; position:absolute; bottom:0; left:18px; right:18px; height:1px; background:var(--gold-line); opacity:.25; }
.panel-title { font-size:10px; font-weight:600; letter-spacing:.14em; text-transform:uppercase; color:var(--muted); display:flex; align-items:center; gap:8px; }
.panel-dot { width:5px; height:5px; border-radius:50%; }
.panel-body { padding:18px; }

/* ── TABLES ── */
.dt { width:100%; border-collapse:collapse; font-size:12px; }
.dt th { text-align:left; padding:10px 16px; font-size:9px; font-weight:600; letter-spacing:.12em; text-transform:uppercase; color:var(--muted); border-bottom:1px solid var(--border); background:var(--deep); }
.dt td { padding:12px 16px; border-bottom:1px solid rgba(37,39,41,.6); font-family:var(--mono); font-size:12px; color:var(--text2); }
.dt tr:last-child td { border-bottom:none; }
.dt tr { transition:background .15s; }
.dt tr:hover td { background:var(--raised); cursor:pointer; }
.dt .pair { font-weight:600; color:var(--text); font-family:var(--sans); font-size:12px; }

/* ── BADGES ── */
.badge { display:inline-flex; align-items:center; padding:2px 9px; border-radius:4px; font-size:9px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; font-family:var(--sans); }
.b-buy  { background:rgba(34,201,122,.1); color:var(--green); border:1px solid rgba(34,201,122,.2); }
.b-sell { background:rgba(255,75,75,.1);  color:var(--red);   border:1px solid rgba(255,75,75,.2); }
.b-tp   { background:rgba(34,201,122,.1); color:var(--green); border:1px solid rgba(34,201,122,.2); }
.b-sl   { background:rgba(255,75,75,.1);  color:var(--red);   border:1px solid rgba(255,75,75,.2); }
.b-gold { background:rgba(201,168,76,.1); color:var(--gold);  border:1px solid rgba(201,168,76,.2); }

/* ── COLOURS ── */
.tg { color:var(--green); }
.tr { color:var(--red); }
.tb { color:var(--blue); }
.tgold { color:var(--gold); }
.tm { color:var(--muted); }
.td { color:var(--dim); }

/* ── STAT GRID ── */
.sg { display:grid; grid-template-columns:repeat(2,1fr); gap:1px; background:var(--border); }
.sc { background:var(--surface); padding:14px 16px; }
.sc-l { font-size:9px; color:var(--muted); text-transform:uppercase; letter-spacing:.1em; margin-bottom:4px; }
.sc-v { font-family:var(--mono); font-size:15px; font-weight:600; color:var(--text); }

/* ── RISK ── */
.ri { margin-bottom:14px; }
.ri:last-child { margin-bottom:0; }
.rr { display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; }
.rl { font-size:11px; color:var(--dim); }
.rv { font-family:var(--mono); font-size:11px; color:var(--text2); }
.rb { height:4px; background:rgba(37,39,41,.8); border-radius:2px; overflow:hidden; }
.rf { height:100%; border-radius:2px; transition:width 1s ease, background .5s; }

/* ── INSTRUMENT ROW ── */
.ir { display:flex; align-items:center; padding:9px 0; border-bottom:1px solid rgba(37,39,41,.6); gap:10px; }
.ir:last-child { border-bottom:none; }
.in { flex:1; font-size:11px; font-weight:500; color:var(--dim); letter-spacing:.04em; }
.it { font-family:var(--mono); font-size:11px; color:var(--muted); width:36px; text-align:right; }
.iw { font-family:var(--mono); font-size:11px; width:40px; text-align:right; }
.ib { width:56px; height:3px; background:var(--border2); border-radius:2px; overflow:hidden; }
.if { height:100%; border-radius:2px; }
.ip { font-family:var(--mono); font-size:12px; font-weight:600; width:68px; text-align:right; }

/* ── POSITION CARD ── */
.pc { border:1px solid var(--border); border-radius:9px; overflow:hidden; margin-bottom:10px; cursor:pointer; transition:border-color .2s, box-shadow .2s; }
.pc:hover { border-color:rgba(201,168,76,.4); box-shadow:0 0 20px rgba(201,168,76,.06); }
.pc-h { display:flex; justify-content:space-between; align-items:center; padding:12px 16px; background:var(--raised); border-bottom:1px solid var(--border); }
.pc-pair { font-weight:700; font-size:14px; letter-spacing:.03em; }
.pc-pnl  { font-family:var(--mono); font-size:14px; font-weight:600; }
.pc-b { padding:12px 16px; display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }
.pf-l { font-size:9px; text-transform:uppercase; letter-spacing:.1em; color:var(--muted); margin-bottom:3px; }
.pf-v { font-family:var(--mono); font-size:12px; font-weight:500; color:var(--text2); }
.pc-prog { height:2px; background:var(--border2); margin:0 16px 12px; overflow:hidden; border-radius:1px; }
.pc-fill { height:100%; border-radius:1px; transition:width .6s; }

/* ── PRICE GRID ── */
.pg { display:grid; grid-template-columns:repeat(3,1fr); gap:1px; background:var(--border); }
.p-cell { background:var(--surface); padding:14px 16px; transition:background .15s; }
.p-cell:hover { background:var(--raised); }
.p-pair { font-size:10px; font-weight:600; letter-spacing:.1em; color:var(--muted); margin-bottom:5px; }
.p-mid  { font-family:var(--mono); font-size:17px; font-weight:600; color:var(--text); transition:color .3s; }
.p-mid.up   { color:var(--green2); }
.p-mid.down { color:var(--red2); }
.p-bot { display:flex; justify-content:space-between; margin-top:5px; }
.p-sp  { font-family:var(--mono); font-size:10px; color:var(--muted); }
.p-bar { height:2px; background:var(--border2); border-radius:1px; margin-top:6px; overflow:hidden; }
.p-fill { height:100%; background:linear-gradient(90deg,var(--gold-dim),var(--gold)); border-radius:1px; transition:width .5s; }

/* ── EMPTY ── */
.empty { text-align:center; padding:48px 20px; color:var(--muted); }
.empty-icon { font-size:30px; margin-bottom:12px; opacity:.3; }
.empty-text { font-size:13px; }
.empty-sub  { font-size:11px; color:var(--border2); margin-top:5px; }

/* ── MODAL ── */
.modal-ov { display:none; position:fixed; inset:0; background:rgba(4,4,6,.9); z-index:200; align-items:center; justify-content:center; backdrop-filter:blur(6px); }
.modal-ov.open { display:flex; }
.modal { background:var(--surface); border:1px solid rgba(201,168,76,.2); border-radius:12px; width:90%; max-width:840px; overflow:hidden; animation:mIn .2s ease; box-shadow:0 0 60px rgba(201,168,76,.08); }
@keyframes mIn { from{opacity:0;transform:scale(.96) translateY(10px)} to{opacity:1;transform:none} }
.modal-h { display:flex; justify-content:space-between; align-items:center; padding:16px 20px; border-bottom:1px solid var(--border); position:relative; }
.modal-h::after { content:''; position:absolute; bottom:0; left:0; right:0; height:1px; background:var(--gold-line); opacity:.3; }
.modal-t { font-size:13px; font-weight:600; color:var(--text); }
.modal-acts { display:flex; gap:8px; align-items:center; }
.m-btn { background:var(--raised); border:1px solid var(--border2); color:var(--dim); padding:5px 12px; border-radius:6px; cursor:pointer; font-size:11px; font-family:var(--sans); transition:all .2s; }
.m-btn:hover { color:var(--gold); border-color:rgba(201,168,76,.3); }
.m-close { background:none; border:none; color:var(--muted); font-size:18px; cursor:pointer; padding:4px 8px; line-height:1; transition:color .2s; }
.m-close:hover { color:var(--text); }

/* ── SCROLLBAR ── */
::-webkit-scrollbar { width:4px; height:4px; }
::-webkit-scrollbar-track { background:var(--deep); }
::-webkit-scrollbar-thumb { background:var(--border2); border-radius:2px; }
::-webkit-scrollbar-thumb:hover { background:var(--gold-dim); }

/* ── ANIMATIONS ── */
.fade { animation:fadeIn .35s ease; }
@keyframes fadeIn { from{opacity:0;transform:translateY(5px)} to{opacity:1;transform:none} }
@keyframes spin { to{transform:rotate(360deg)} }

/* ── GOLD DIVIDER ── */
.gold-div { height:1px; background:var(--gold-line); opacity:.3; margin:16px 0; }

/* ── SECTION LABEL ── */
.section-eyebrow { font-size:9px; font-weight:700; letter-spacing:.2em; text-transform:uppercase; color:var(--gold-dim); margin-bottom:16px; display:flex; align-items:center; gap:10px; }
.section-eyebrow::after { content:''; flex:1; height:1px; background:var(--border2); }
</style>
</head>
<body>

<!-- TICKER -->
<div class="ticker-wrap">
  <div class="ticker-track" id="tt">
    <div class="ticker-item"><span class="ticker-pair">EUR/USD</span><span class="ticker-price" id="t-EUR_USD">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">GBP/USD</span><span class="ticker-price" id="t-GBP_USD">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">USD/JPY</span><span class="ticker-price" id="t-USD_JPY">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">EUR/JPY</span><span class="ticker-price" id="t-EUR_JPY">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">GBP/JPY</span><span class="ticker-price" id="t-GBP_JPY">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">XAU/USD</span><span class="ticker-price" id="t-XAU_USD">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">AUD/USD</span><span class="ticker-price" id="t-AUD_USD">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">USD/CAD</span><span class="ticker-price" id="t-USD_CAD">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">NZD/USD</span><span class="ticker-price" id="t-NZD_USD">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">EUR/GBP</span><span class="ticker-price" id="t-EUR_GBP">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">USD/CHF</span><span class="ticker-price" id="t-USD_CHF">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">XAG/USD</span><span class="ticker-price" id="t-XAG_USD">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">EUR/USD</span><span class="ticker-price" id="t2-EUR_USD">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">GBP/USD</span><span class="ticker-price" id="t2-GBP_USD">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">USD/JPY</span><span class="ticker-price" id="t2-USD_JPY">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">EUR/JPY</span><span class="ticker-price" id="t2-EUR_JPY">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">GBP/JPY</span><span class="ticker-price" id="t2-GBP_JPY">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">XAU/USD</span><span class="ticker-price" id="t2-XAU_USD">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">AUD/USD</span><span class="ticker-price" id="t2-AUD_USD">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">USD/CAD</span><span class="ticker-price" id="t2-USD_CAD">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">NZD/USD</span><span class="ticker-price" id="t2-NZD_USD">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">EUR/GBP</span><span class="ticker-price" id="t2-EUR_GBP">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">USD/CHF</span><span class="ticker-price" id="t2-USD_CHF">—</span><span class="ticker-dot up"></span></div>
    <div class="ticker-item"><span class="ticker-pair">XAG/USD</span><span class="ticker-price" id="t2-XAG_USD">—</span><span class="ticker-dot up"></span></div>
  </div>
</div>

<!-- HEADER -->
<header>
  <div class="logo">
    <div class="logo-a">A</div>
    <div class="logo-text-wrap">
      <div class="logo-name">ATLASFX</div>
      <div class="logo-tag">Automated · Intelligent · Unstoppable</div>
    </div>
    <div class="header-divider"></div>
    <div class="header-center" style="display:flex;align-items:center;gap:4px">
      <div class="nav-tab active" onclick="showView('overview',this)">Overview</div>
      <div class="nav-tab" onclick="showView('positions',this)">Positions</div>
      <div class="nav-tab" onclick="showView('markets',this)">Markets</div>
      <div class="nav-tab" onclick="showView('analytics',this)">Analytics</div>
      <div class="nav-tab" onclick="showView('history',this)">History</div>
    </div>
  </div>
  <div class="header-right">
    <div class="scan-ind"><div class="scan-ring"></div><span>LIVE SCAN</span></div>
    <div class="live-badge"><div class="live-dot"></div>DEMO ACCOUNT</div>
    <div class="clock" id="clock">00:00:00 UTC</div>
    <button class="refresh-btn" id="rbtn" onclick="loadAll()"><span class="refresh-spin">↻</span> Refresh</button>
  </div>
</header>

<div class="main">

<!-- ══ OVERVIEW ══ -->
<div class="view active" id="view-overview">
  <div class="kpi-row">
    <div class="kpi"><div class="kpi-label">Account Balance</div><div class="kpi-value gold" id="kpi-balance">—</div><div class="kpi-sub" id="kpi-curr">GBP Practice</div><div class="kpi-bg">⚖</div></div>
    <div class="kpi"><div class="kpi-label">Net Asset Value</div><div class="kpi-value" id="kpi-nav">—</div><div class="kpi-sub" id="kpi-unr">Unrealised P&L</div><div class="kpi-bg">◈</div></div>
    <div class="kpi"><div class="kpi-label">Total P&L</div><div class="kpi-value" id="kpi-pnl">—</div><div class="kpi-sub" id="kpi-tc">— trades</div><div class="kpi-bg">▲</div></div>
    <div class="kpi"><div class="kpi-label">Win Rate</div><div class="kpi-value" id="kpi-wr">—</div><div class="kpi-sub" id="kpi-pf">Profit factor —</div><div class="kpi-bg">◎</div></div>
    <div class="kpi"><div class="kpi-label">Open Positions</div><div class="kpi-value tgold" id="kpi-open">—</div><div class="kpi-sub" id="kpi-exp">— exposure</div><div class="kpi-bg">⚡</div></div>
  </div>

  <div class="g73">
    <div class="panel">
      <div class="panel-header">
        <div class="panel-title"><div class="panel-dot" style="background:var(--gold)"></div>EQUITY CURVE</div>
        <span style="font-size:10px;color:var(--muted)">All time performance</span>
      </div>
      <div style="padding:16px 8px 8px"><canvas id="ec1" height="220" style="width:100%;display:block"></canvas></div>
    </div>
    <div class="panel">
      <div class="panel-header">
        <div class="panel-title"><div class="panel-dot" style="background:var(--green)"></div>OPEN POSITIONS</div>
        <span style="font-size:10px;color:var(--muted)" id="pc1">0 active</span>
      </div>
      <div style="padding:12px" id="op-cards">
        <div class="empty"><div class="empty-icon">◎</div><div class="empty-text">No open positions</div><div class="empty-sub">Scanning every 15 minutes</div></div>
      </div>
    </div>
  </div>

  <div class="g3">
    <div class="panel">
      <div class="panel-header"><div class="panel-title"><div class="panel-dot" style="background:var(--gold)"></div>PERFORMANCE METRICS</div></div>
      <div class="sg">
        <div class="sc"><div class="sc-l">Avg R Multiple</div><div class="sc-v" id="s-ar">—</div></div>
        <div class="sc"><div class="sc-l">Profit Factor</div><div class="sc-v" id="s-pf">—</div></div>
        <div class="sc"><div class="sc-l">Best Trade</div><div class="sc-v tg" id="s-best">—</div></div>
        <div class="sc"><div class="sc-l">Worst Trade</div><div class="sc-v tr" id="s-worst">—</div></div>
        <div class="sc"><div class="sc-l">Avg Win</div><div class="sc-v tg" id="s-aw">—</div></div>
        <div class="sc"><div class="sc-l">Avg Loss</div><div class="sc-v tr" id="s-al">—</div></div>
        <div class="sc"><div class="sc-l">Today Trades</div><div class="sc-v" id="s-tt">—</div></div>
        <div class="sc"><div class="sc-l">Today P&L</div><div class="sc-v" id="s-tp">—</div></div>
      </div>
    </div>
    <div class="panel">
      <div class="panel-header"><div class="panel-title"><div class="panel-dot" style="background:var(--red)"></div>RISK MONITOR</div></div>
      <div class="panel-body">
        <div class="ri"><div class="rr"><span class="rl">Daily Drawdown</span><span class="rv" id="r-dd">0.00%</span></div><div class="rb"><div class="rf" id="r-ddf" style="width:0%;background:var(--green)"></div></div></div>
        <div class="ri"><div class="rr"><span class="rl">Weekly Drawdown</span><span class="rv" id="r-wd">0.00%</span></div><div class="rb"><div class="rf" id="r-wdf" style="width:0%;background:var(--green)"></div></div></div>
        <div class="ri"><div class="rr"><span class="rl">Open Exposure</span><span class="rv" id="r-exp">0.00%</span></div><div class="rb"><div class="rf" id="r-expf" style="width:0%;background:var(--gold)"></div></div></div>
        <div class="gold-div"></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;font-size:11px">
          <div><div style="color:var(--muted);margin-bottom:3px;font-size:9px;letter-spacing:.1em;text-transform:uppercase">Risk / Trade</div><div style="font-family:var(--mono);color:var(--text2)" id="r-pt">0.5%</div></div>
          <div><div style="color:var(--muted);margin-bottom:3px;font-size:9px;letter-spacing:.1em;text-transform:uppercase">Max Exposure</div><div style="font-family:var(--mono);color:var(--text2)">3.0%</div></div>
          <div><div style="color:var(--muted);margin-bottom:3px;font-size:9px;letter-spacing:.1em;text-transform:uppercase">Daily Limit</div><div style="font-family:var(--mono);color:var(--text2)">2.0%</div></div>
          <div><div style="color:var(--muted);margin-bottom:3px;font-size:9px;letter-spacing:.1em;text-transform:uppercase">Weekly Limit</div><div style="font-family:var(--mono);color:var(--text2)">5.0%</div></div>
        </div>
      </div>
    </div>
    <div class="panel">
      <div class="panel-header"><div class="panel-title"><div class="panel-dot" style="background:var(--gold)"></div>TOP INSTRUMENTS</div></div>
      <div class="panel-body" id="inst-panel"><div class="empty"><div class="empty-text">No trade data yet</div></div></div>
    </div>
  </div>

  <div class="panel gap">
    <div class="panel-header"><div class="panel-title"><div class="panel-dot" style="background:var(--gold)"></div>RECENT CLOSED TRADES</div><span style="font-size:10px;color:var(--muted)">Last 10</span></div>
    <div style="overflow-x:auto" id="recent-panel"><div class="empty"><div class="empty-icon">◈</div><div class="empty-text">No closed trades yet</div></div></div>
  </div>
</div>

<!-- ══ POSITIONS ══ -->
<div class="view" id="view-positions">
  <div class="panel gap">
    <div class="panel-header"><div class="panel-title"><div class="panel-dot" style="background:var(--green)"></div>OPEN POSITIONS</div><span style="font-size:10px;color:var(--muted)" id="pc2">0 active</span></div>
    <div style="overflow-x:auto">
      <table class="dt"><thead><tr><th>Pair</th><th>Direction</th><th>Entry</th><th>Stop Loss</th><th>Take Profit</th><th>P&L Pips</th><th>Strategy</th><th>Opened</th></tr></thead>
      <tbody id="pos-tb"><tr><td colspan="8"><div class="empty">No open positions</div></td></tr></tbody></table>
    </div>
  </div>
</div>

<!-- ══ MARKETS ══ -->
<div class="view" id="view-markets">
  <div class="panel gap">
    <div class="panel-header"><div class="panel-title"><div class="panel-dot" style="background:var(--gold)"></div>LIVE MARKET PRICES</div><span style="font-size:10px;color:var(--muted)">12 instruments · auto-refresh every 30s</span></div>
    <div class="pg" id="mkt-grid"></div>
  </div>
</div>

<!-- ══ ANALYTICS ══ -->
<div class="view" id="view-analytics">
  <div class="g2 gap">
    <div class="panel">
      <div class="panel-header"><div class="panel-title"><div class="panel-dot" style="background:var(--gold)"></div>EQUITY CURVE</div></div>
      <div style="padding:16px 8px 8px"><canvas id="ec2" height="220" style="width:100%;display:block"></canvas></div>
    </div>
    <div class="panel">
      <div class="panel-header"><div class="panel-title"><div class="panel-dot" style="background:var(--gold)"></div>BY INSTRUMENT</div></div>
      <div style="overflow-x:auto">
        <table class="dt"><thead><tr><th>Pair</th><th>Trades</th><th>Win %</th><th>P&L</th></tr></thead>
        <tbody id="inst-tb"><tr><td colspan="4"><div class="empty">No data yet</div></td></tr></tbody></table>
      </div>
    </div>
  </div>
  <div class="panel gap">
    <div class="panel-header"><div class="panel-title"><div class="panel-dot" style="background:var(--gold)"></div>FULL PERFORMANCE BREAKDOWN</div></div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--border)">
      <div class="sc"><div class="sc-l">Total Trades</div><div class="sc-v" id="a-total">—</div></div>
      <div class="sc"><div class="sc-l">Winning</div><div class="sc-v tg" id="a-wins">—</div></div>
      <div class="sc"><div class="sc-l">Losing</div><div class="sc-v tr" id="a-losses">—</div></div>
      <div class="sc"><div class="sc-l">Win Rate</div><div class="sc-v" id="a-wr">—</div></div>
      <div class="sc"><div class="sc-l">Total P&L</div><div class="sc-v" id="a-pnl">—</div></div>
      <div class="sc"><div class="sc-l">Profit Factor</div><div class="sc-v" id="a-pf">—</div></div>
      <div class="sc"><div class="sc-l">Avg R</div><div class="sc-v" id="a-ar">—</div></div>
      <div class="sc"><div class="sc-l">Best Trade</div><div class="sc-v tg" id="a-best">—</div></div>
    </div>
  </div>
</div>

<!-- ══ HISTORY ══ -->
<div class="view" id="view-history">
  <div class="panel">
    <div class="panel-header"><div class="panel-title"><div class="panel-dot" style="background:var(--gold)"></div>TRADE HISTORY</div><span style="font-size:10px;color:var(--muted)">Last 100 closed trades</span></div>
    <div style="overflow-x:auto">
      <table class="dt"><thead><tr><th>Pair</th><th>Dir</th><th>Entry</th><th>Exit</th><th>P&L</th><th>R</th><th>Strategy</th><th>Reason</th><th>Closed</th></tr></thead>
      <tbody id="hist-tb"><tr><td colspan="9"><div class="empty">No closed trades yet</div></td></tr></tbody></table>
    </div>
  </div>
</div>

</div><!-- .main -->

<!-- CHART MODAL -->
<div class="modal-ov" id="modal" onclick="if(event.target===this)closeModal()">
  <div class="modal">
    <div class="modal-h">
      <div class="modal-t" id="modal-t">Trade Chart</div>
      <div class="modal-acts">
        <button class="m-btn" onclick="refreshChart()">↻ Refresh</button>
        <button class="m-close" onclick="closeModal()">✕</button>
      </div>
    </div>
    <canvas id="tc" height="360" style="width:100%;display:block"></canvas>
  </div>
</div>

<script>
const $=id=>document.getElementById(id);
const fN=(n,d=2)=>n==null?'—':n.toFixed(d);
const fS=(n,d=2)=>n==null?'—':((n>=0?'+':'')+n.toFixed(d));
const cls=n=>n>0?'tg':n<0?'tr':'td';
const dec=i=>(i.includes('JPY')||i.includes('XAU')||i.includes('XAG'))?3:5;
const pip=i=>(i.includes('JPY')||i.includes('XAU')||i.includes('XAG'))?0.01:0.0001;
async function fj(u){try{const r=await fetch(u);return await r.json()}catch{return null}}
let _prev={},_ct=null;

// Clock
setInterval(()=>{const n=new Date();$('clock').textContent=n.toUTCString().slice(17,25)+' UTC'},1000);

// Nav
function showView(id,el){
  document.querySelectorAll('.view').forEach(v=>v.classList.remove('active'));
  document.querySelectorAll('.nav-tab').forEach(t=>t.classList.remove('active'));
  $('view-'+id).classList.add('active');el.classList.add('active');
  if(id==='markets')loadMarkets();
  if(id==='analytics'){loadAnalytics();drawEq('ec2')();}
  if(id==='history')loadHistory();
  if(id==='positions')loadPosView();
}

// Ticker update
async function updateTicker(){
  const d=await fj('/api/prices');if(!d)return;
  for(const[inst,p]of Object.entries(d)){
    if(p.error)continue;
    const pr=p.mid.toFixed(dec(inst));const prev=_prev[inst];
    const up=prev?p.mid>=prev:true;_prev[inst]=p.mid;
    ['t-'+inst,'t2-'+inst].forEach(id=>{
      const el=$(id);if(!el)return;
      el.textContent=pr;
      el.className='ticker-price '+(up?'up':'down');
      setTimeout(()=>el.className='ticker-price',1000);
    });
  }
}

// Account
async function loadAccount(){
  const d=await fj('/api/account');if(!d||d.error)return;
  $('kpi-balance').textContent=d.balance.toLocaleString('en-GB',{minimumFractionDigits:2,maximumFractionDigits:2});
  $('kpi-nav').textContent=d.nav.toLocaleString('en-GB',{minimumFractionDigits:2,maximumFractionDigits:2});
  $('kpi-curr').textContent=(d.currency||'GBP')+' Practice Account';
  $('kpi-open').textContent=d.open_trade_count;
  const u=$('kpi-unr');const un=d.unrealised_pnl||0;
  u.textContent=(un>=0?'+':'')+fN(un)+' unrealised';
  u.className='kpi-sub '+(un>=0?'pos':'neg');
}

// Stats
async function loadStats(){
  const d=await fj('/api/stats');if(!d)return;
  const pnl=$('kpi-pnl');pnl.textContent=fS(d.total_pnl);pnl.className='kpi-value '+cls(d.total_pnl);
  $('kpi-tc').textContent=(d.total_trades||0)+' closed trades';
  $('kpi-wr').textContent=fN(d.win_rate_pct,1)+'%';
  $('kpi-pf').textContent='Profit factor '+fN(d.profit_factor,3);
  const ar=$('s-ar');ar.textContent=fS(d.avg_r_multiple,3)+'R';ar.className='sc-v '+cls(d.avg_r_multiple);
  $('s-pf').textContent=fN(d.profit_factor,3);
  $('s-best').textContent=fS(d.best_trade);$('s-worst').textContent=fS(d.worst_trade);
  $('s-aw').textContent=fS(d.avg_win);$('s-al').textContent=fS(d.avg_loss);
  $('s-tt').textContent=d.total_trades_today||0;
  const tp=$('s-tp');tp.textContent=fS(d.pnl_today);tp.className='sc-v '+cls(d.pnl_today);
  $('a-total').textContent=d.total_trades||0;$('a-wins').textContent=d.winning_trades||0;
  $('a-losses').textContent=d.losing_trades||0;$('a-wr').textContent=fN(d.win_rate_pct,1)+'%';
  const ap=$('a-pnl');ap.textContent=fS(d.total_pnl);ap.className='sc-v '+cls(d.total_pnl);
  $('a-pf').textContent=fN(d.profit_factor,3);
  const ar2=$('a-ar');ar2.textContent=fS(d.avg_r_multiple,3)+'R';ar2.className='sc-v '+cls(d.avg_r_multiple);
  $('a-best').textContent=fS(d.best_trade);
}

// Risk
async function loadRisk(){
  const d=await fj('/api/risk');if(!d)return;
  $('r-pt').textContent=(d.risk_per_trade_pct||0.5)+'%';
  if(d.balance)$('kpi-balance').textContent=d.balance.toLocaleString('en-GB',{minimumFractionDigits:2,maximumFractionDigits:2});
}

// Open positions
async function loadOpen(){
  const[td,pr]=await Promise.all([fj('/api/trades/open'),fj('/api/prices')]);
  const n=td?td.length:0;
  $('kpi-open').textContent=n;
  $('kpi-exp').textContent=(n*0.75).toFixed(2)+'% exposure';
  if($('pc1'))$('pc1').textContent=n+' active';
  if($('pc2'))$('pc2').textContent=n+' active';
  const el=$('op-cards');
  if(!td||!td.length){
    el.innerHTML='<div class="empty"><div class="empty-icon">◎</div><div class="empty-text">No open positions</div><div class="empty-sub">Scanning every 15 minutes</div></div>';
    return;
  }
  el.innerHTML='';
  td.forEach(t=>{
    const cur=pr&&pr[t.instrument]?pr[t.instrument].mid:t.entry_price;
    const p=pip(t.instrument),d=dec(t.instrument);
    const pp=((t.direction==='BUY'?cur-t.entry_price:t.entry_price-cur)/p).toFixed(1);
    const inP=parseFloat(pp)>=0;
    const rng=Math.abs(t.take_profit-t.stop_loss);
    const prog=rng>0?Math.min(Math.abs(cur-t.entry_price)/rng,1)*100:0;
    const card=document.createElement('div');card.className='pc fade';
    card.onclick=()=>showChart(t);
    card.innerHTML=`<div class="pc-h">
      <div style="display:flex;align-items:center;gap:10px">
        <span class="pc-pair" style="font-weight:700;font-size:14px;letter-spacing:.03em">${t.instrument.replace('_','/')}</span>
        <span class="badge ${t.direction==='BUY'?'b-buy':'b-sell'}">${t.direction}</span>
      </div>
      <span class="pc-pnl ${inP?'tg':'tr'}">${inP?'+':''}${pp} pips</span>
    </div>
    <div class="pc-b">
      <div><div class="pf-l">Entry</div><div class="pf-v tb">${(t.entry_price||0).toFixed(d)}</div></div>
      <div><div class="pf-l">Stop Loss</div><div class="pf-v tr">${(t.stop_loss||0).toFixed(d)}</div></div>
      <div><div class="pf-l">Take Profit</div><div class="pf-v tg">${(t.take_profit||0).toFixed(d)}</div></div>
      <div><div class="pf-l">Current</div><div class="pf-v">${cur.toFixed(d)}</div></div>
      <div><div class="pf-l">Strategy</div><div class="pf-v td" style="font-size:10px">${(t.strategy_id||'—').replace('_H1_V1','')}</div></div>
      <div><div class="pf-l">Opened</div><div class="pf-v td" style="font-size:10px">${(t.open_time||'').slice(11,16)} UTC</div></div>
    </div>
    <div class="pc-prog"><div class="pc-fill" style="width:${prog}%;background:${inP?'var(--green)':'var(--red)'}"></div></div>`;
    el.appendChild(card);
  });
}

// Positions table view
async function loadPosView(){
  const[td,pr]=await Promise.all([fj('/api/trades/open'),fj('/api/prices')]);
  const tb=$('pos-tb');
  if(!td||!td.length){tb.innerHTML='<tr><td colspan="8"><div class="empty">No open positions</div></td></tr>';return;}
  tb.innerHTML=td.map(t=>{
    const cur=pr&&pr[t.instrument]?pr[t.instrument].mid:t.entry_price;
    const p=pip(t.instrument),d=dec(t.instrument);
    const pp=((t.direction==='BUY'?cur-t.entry_price:t.entry_price-cur)/p).toFixed(1);
    const inP=parseFloat(pp)>=0;
    return `<tr onclick='showChart(${JSON.stringify(t)})'>
      <td class="pair">${t.instrument.replace('_','/')}</td>
      <td><span class="badge ${t.direction==='BUY'?'b-buy':'b-sell'}">${t.direction}</span></td>
      <td class="tb">${(t.entry_price||0).toFixed(d)}</td>
      <td class="tr">${(t.stop_loss||0).toFixed(d)}</td>
      <td class="tg">${(t.take_profit||0).toFixed(d)}</td>
      <td class="${inP?'tg':'tr'}">${inP?'+':''}${pp}</td>
      <td class="td" style="font-size:11px">${(t.strategy_id||'—').replace('_H1_V1','')}</td>
      <td class="td">${(t.open_time||'').slice(0,16).replace('T',' ')}</td>
    </tr>`;
  }).join('');
}

// Markets
async function loadMarkets(){
  const d=await fj('/api/prices');if(!d)return;
  const grid=$('mkt-grid');grid.innerHTML='';
  for(const[inst,p]of Object.entries(d)){
    if(p.error)continue;
    const d2=dec(inst);const prev=_prev[inst];const up=prev?p.mid>=prev:true;
    const fill=Math.min(p.spread_pips/3*100,100);
    const cell=document.createElement('div');cell.className='p-cell';
    cell.innerHTML=`<div class="p-pair">${inst.replace('_','/')}</div>
      <div class="p-mid ${up?'up':'down'}">${p.mid.toFixed(d2)}</div>
      <div class="p-bot"><span class="p-sp">${p.spread_pips}p spread</span><span style="font-size:10px;color:var(--muted)">${up?'▲':'▼'}</span></div>
      <div class="p-bar"><div class="p-fill" style="width:${fill}%"></div></div>`;
    grid.appendChild(cell);
  }
  updateTicker();
}

// Instrument breakdown
async function loadInstBreakdown(){
  const d=await fj('/api/by-instrument');const el=$('inst-panel');
  if(!d||!Object.keys(d).length){el.innerHTML='<div class="empty"><div class="empty-text">No trade data yet</div></div>';return;}
  const sorted=Object.entries(d).sort((a,b)=>b[1].pnl-a[1].pnl).slice(0,6);
  const maxP=Math.max(...sorted.map(([,v])=>Math.abs(v.pnl)),1);
  el.innerHTML=sorted.map(([inst,s])=>{
    const pc=s.pnl>=0?'var(--green)':'var(--red)';
    const fw=Math.min(Math.abs(s.pnl)/maxP*100,100);
    const wr=s.win_rate||0;
    return `<div class="ir">
      <div class="in">${inst.replace('_','/')}</div>
      <div class="it tm">${s.trades}t</div>
      <div class="iw" style="color:${wr>=50?'var(--green)':'var(--red)'}">${wr}%</div>
      <div class="ib"><div class="if" style="width:${fw}%;background:${pc}"></div></div>
      <div class="ip" style="color:${pc}">${fS(s.pnl)}</div>
    </div>`;
  }).join('');
}

// Analytics instrument table
async function loadAnalytics(){
  const d=await fj('/api/by-instrument');const tb=$('inst-tb');
  if(!d||!Object.keys(d).length){tb.innerHTML='<tr><td colspan="4"><div class="empty">No data</div></td></tr>';return;}
  tb.innerHTML=Object.entries(d).sort((a,b)=>b[1].pnl-a[1].pnl).map(([inst,s])=>
    `<tr><td class="pair">${inst.replace('_','/')}</td><td>${s.trades}</td>
    <td class="${s.win_rate>=50?'tg':'tr'}">${s.win_rate}%</td>
    <td class="${cls(s.pnl)}"><b>${fS(s.pnl)}</b></td></tr>`).join('');
}

// Recent trades
async function loadRecent(){
  const d=await fj('/api/trades/closed');const el=$('recent-panel');
  if(!d||!d.length){el.innerHTML='<div class="empty"><div class="empty-icon">◈</div><div class="empty-text">No closed trades yet</div></div>';return;}
  const last=[...d].reverse().slice(0,10);
  el.innerHTML=`<table class="dt"><thead><tr><th>Pair</th><th>Dir</th><th>Entry</th><th>Exit</th><th>P&L</th><th>R</th><th>Reason</th><th>Time</th></tr></thead><tbody>
    ${last.map(t=>`<tr onclick='showChart(${JSON.stringify(t)})'>
      <td class="pair">${t.instrument.replace('_','/')}</td>
      <td><span class="badge ${t.direction==='BUY'?'b-buy':'b-sell'}">${t.direction}</span></td>
      <td>${(t.entry_price||0).toFixed(dec(t.instrument))}</td>
      <td>${(t.exit_price||0).toFixed(dec(t.instrument))}</td>
      <td class="${cls(t.pnl)}"><b>${fS(t.pnl)}</b></td>
      <td class="${cls(t.r_multiple)}">${fS(t.r_multiple,2)}R</td>
      <td><span class="badge ${t.close_reason==='take_profit'?'b-tp':'b-sl'}">${(t.close_reason||'—').replace('_',' ')}</span></td>
      <td class="td">${(t.close_time||'').slice(11,16)} UTC</td>
    </tr>`).join('')}
  </tbody></table>`;
}

// History
async function loadHistory(){
  const d=await fj('/api/trades/closed');const tb=$('hist-tb');
  if(!d||!d.length){tb.innerHTML='<tr><td colspan="9"><div class="empty">No closed trades yet</div></td></tr>';return;}
  tb.innerHTML=[...d].reverse().map(t=>`<tr onclick='showChart(${JSON.stringify(t)})'>
    <td class="pair">${t.instrument.replace('_','/')}</td>
    <td><span class="badge ${t.direction==='BUY'?'b-buy':'b-sell'}">${t.direction}</span></td>
    <td>${(t.entry_price||0).toFixed(dec(t.instrument))}</td>
    <td>${(t.exit_price||0).toFixed(dec(t.instrument))}</td>
    <td class="${cls(t.pnl)}"><b>${fS(t.pnl)}</b></td>
    <td class="${cls(t.r_multiple)}">${fS(t.r_multiple,2)}R</td>
    <td class="td" style="font-size:11px">${(t.strategy_id||'—').replace('_H1_V1','')}</td>
    <td><span class="badge ${t.close_reason==='take_profit'?'b-tp':'b-sl'}">${(t.close_reason||'—').replace('_',' ')}</span></td>
    <td class="td">${(t.close_time||'').slice(0,16).replace('T',' ')}</td>
  </tr>`).join('');
}

// Equity chart - gold themed
function drawEq(cid){return async()=>{
  const d=await fj('/api/equity');const canvas=$(cid);
  if(!d||!d.length||!canvas)return;
  const ctx=canvas.getContext('2d');
  const W=canvas.offsetWidth||800;const H=canvas.height;canvas.width=W;
  const vals=d.map(p=>p.equity);
  const mn=Math.min(...vals);const mx=Math.max(...vals);
  const pad={t:30,b:40,l:85,r:20};
  const toX=i=>pad.l+(i/(d.length-1||1))*(W-pad.l-pad.r);
  const toY=v=>pad.t+((mx-v)/(mx-mn||1))*(H-pad.t-pad.b);
  // BG
  ctx.fillStyle='#0C0D0F';ctx.fillRect(0,0,W,H);
  // Grid
  ctx.strokeStyle='rgba(37,39,41,.6)';ctx.lineWidth=.5;ctx.setLineDash([2,4]);
  for(let i=0;i<=5;i++){
    const pv=mn+(mx-mn)*(i/5);const y=toY(pv);
    ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(W-pad.r,y);ctx.stroke();
    ctx.fillStyle='#5A5650';ctx.font='10px JetBrains Mono,monospace';ctx.textAlign='right';
    ctx.fillText(pv.toLocaleString('en-GB',{maximumFractionDigits:0}),pad.l-6,y+3);
  }
  ctx.setLineDash([]);
  const isP=vals[vals.length-1]>=vals[0];
  // Gold gradient fill
  const grad=ctx.createLinearGradient(0,pad.t,0,H-pad.b);
  if(isP){
    grad.addColorStop(0,'rgba(201,168,76,.3)');
    grad.addColorStop(1,'rgba(201,168,76,.0)');
  } else {
    grad.addColorStop(0,'rgba(255,75,75,.2)');
    grad.addColorStop(1,'rgba(255,75,75,.0)');
  }
  ctx.beginPath();
  d.forEach((p,i)=>i===0?ctx.moveTo(toX(i),toY(p.equity)):ctx.lineTo(toX(i),toY(p.equity)));
  ctx.lineTo(toX(d.length-1),H-pad.b);ctx.lineTo(toX(0),H-pad.b);ctx.closePath();
  ctx.fillStyle=grad;ctx.fill();
  // Gold line
  const lineGrad=ctx.createLinearGradient(pad.l,0,W-pad.r,0);
  lineGrad.addColorStop(0,'#8A6F2E');lineGrad.addColorStop(.5,'#F5DFA0');lineGrad.addColorStop(1,'#8A6F2E');
  ctx.beginPath();
  d.forEach((p,i)=>i===0?ctx.moveTo(toX(i),toY(p.equity)):ctx.lineTo(toX(i),toY(p.equity)));
  ctx.strokeStyle=isP?lineGrad:'#FF4B4B';ctx.lineWidth=2;ctx.setLineDash([]);ctx.stroke();
  // End dot
  const lx=toX(d.length-1);const ly=toY(vals[vals.length-1]);
  ctx.beginPath();ctx.arc(lx,ly,4,0,Math.PI*2);
  ctx.fillStyle=isP?'#C9A84C':'#FF4B4B';ctx.fill();
  ctx.beginPath();ctx.arc(lx,ly,7,0,Math.PI*2);
  ctx.strokeStyle=isP?'rgba(201,168,76,.3)':'rgba(255,75,75,.3)';ctx.lineWidth=1;ctx.stroke();
  // Return label
  const tr=vals[vals.length-1]-vals[0];const pct=(tr/vals[0]*100).toFixed(2);
  ctx.textAlign='left';ctx.fillStyle=isP?'#C9A84C':'#FF4B4B';ctx.font='bold 12px JetBrains Mono,monospace';
  ctx.fillText((isP?'+':'')+tr.toFixed(2)+' ('+pct+'%)',pad.l,18);
  // Dates
  ctx.fillStyle='#3A3830';ctx.font='10px JetBrains Mono,monospace';ctx.textAlign='left';
  if(d.length)ctx.fillText(d[0].date,pad.l,H-8);
  ctx.textAlign='right';if(d.length)ctx.fillText(d[d.length-1].date,W-pad.r,H-8);
}}

const loadEq1=drawEq('ec1');const loadEq2=drawEq('ec2');

// Chart modal
function showChart(trade){_ct=typeof trade==='string'?JSON.parse(trade):trade;$('modal').classList.add('open');renderChart(_ct);}
function closeModal(){$('modal').classList.remove('open');}
function refreshChart(){if(_ct)renderChart(_ct);}

async function renderChart(trade){
  const inst=trade.instrument||'EUR_USD';
  const d=dec(inst);const p=pip(inst);
  const entry=trade.entry_price||0;const sl=trade.stop_loss||0;const tp=trade.take_profit||0;const dir=trade.direction||'BUY';
  $('modal-t').textContent=inst.replace('_','/')+' · '+dir+' · '+(trade.strategy_id||'').replace('_H1_V1','');
  const canvas=$('tc');const ctx=canvas.getContext('2d');
  const W=canvas.offsetWidth||800;const H=360;canvas.width=W;
  ctx.fillStyle='#0C0D0F';ctx.fillRect(0,0,W,H);
  ctx.fillStyle='#5A5650';ctx.font='12px JetBrains Mono,monospace';ctx.textAlign='center';ctx.fillText('Loading candle data...',W/2,H/2);
  const[candles,prices]=await Promise.all([fj('/api/candles/'+inst+'?granularity=M15&count=80'),fj('/api/prices')]);
  const cur=prices&&prices[inst]?prices[inst].mid:entry;
  if(!candles||!candles.length){ctx.fillStyle='#FF4B4B';ctx.fillText('Could not load candle data',W/2,H/2);return;}
  const allP=[...candles.map(c=>c.high),...candles.map(c=>c.low),sl,tp,cur];
  let pmin=Math.min(...allP);let pmax=Math.max(...allP);
  const rng=pmax-pmin;pmin-=rng*.08;pmax+=rng*.08;
  const pad={t:52,b:50,l:92,r:115};
  const cW=Math.max(5,(W-pad.l-pad.r)/candles.length);
  const toY=v=>pad.t+(pmax-v)/(pmax-pmin)*(H-pad.t-pad.b);
  const toX=i=>pad.l+i*cW+cW/2;
  // BG
  ctx.fillStyle='#080809';ctx.fillRect(0,0,W,H);
  // Grid
  ctx.strokeStyle='rgba(37,39,41,.5)';ctx.lineWidth=.5;ctx.setLineDash([2,4]);
  for(let i=0;i<=6;i++){
    const pv=pmin+(pmax-pmin)*(i/6);const y=toY(pv);
    ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(W-pad.r,y);ctx.stroke();
    ctx.fillStyle='#3A3830';ctx.font='9px JetBrains Mono,monospace';ctx.textAlign='right';
    ctx.fillText(pv.toFixed(d),pad.l-4,y+3);
  }
  ctx.setLineDash([]);
  // Zones
  const entY=toY(entry);const tpY=toY(tp);const slY=toY(sl);
  if(dir==='BUY'){
    ctx.fillStyle='rgba(34,201,122,.05)';ctx.fillRect(pad.l,tpY,W-pad.l-pad.r,entY-tpY);
    ctx.fillStyle='rgba(255,75,75,.05)'; ctx.fillRect(pad.l,entY,W-pad.l-pad.r,slY-entY);
  } else {
    ctx.fillStyle='rgba(34,201,122,.05)';ctx.fillRect(pad.l,entY,W-pad.l-pad.r,tpY-entY);
    ctx.fillStyle='rgba(255,75,75,.05)'; ctx.fillRect(pad.l,slY,W-pad.l-pad.r,entY-slY);
  }
  // Candles
  candles.forEach((c,i)=>{
    const x=toX(i);const bull=c.close>=c.open;const col=bull?'#22C97A':'#FF4B4B';
    ctx.strokeStyle=col;ctx.lineWidth=1;ctx.setLineDash([]);
    ctx.beginPath();ctx.moveTo(x,toY(c.high));ctx.lineTo(x,toY(c.low));ctx.stroke();
    const bH=Math.max(1,Math.abs(toY(c.close)-toY(c.open)));
    ctx.fillStyle=bull?'rgba(34,201,122,.8)':'rgba(255,75,75,.8)';
    ctx.fillRect(x-cW*.35,Math.min(toY(c.open),toY(c.close)),cW*.7,bH);
    ctx.strokeStyle=col;ctx.lineWidth=.5;ctx.strokeRect(x-cW*.35,Math.min(toY(c.open),toY(c.close)),cW*.7,bH);
  });
  // Level lines
  const drawL=(price,color,label,bold,dashed)=>{
    const y=toY(price);ctx.strokeStyle=color;ctx.lineWidth=bold?2:1.5;
    ctx.setLineDash(dashed?[5,4]:[]);
    ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(W-pad.r,y);ctx.stroke();ctx.setLineDash([]);
    ctx.fillStyle=color+'18';ctx.fillRect(W-pad.r+2,y-10,pad.r-4,20);
    ctx.strokeStyle=color+'40';ctx.lineWidth=.5;ctx.strokeRect(W-pad.r+2,y-10,pad.r-4,20);
    ctx.fillStyle=color;ctx.font=(bold?'bold ':'')+' 9px JetBrains Mono,monospace';ctx.textAlign='left';
    ctx.fillText(label+' '+price.toFixed(d),W-pad.r+5,y+3);
  };
  drawL(tp,'#22C97A','TP',true,false);drawL(entry,'#C9A84C','IN',true,false);
  drawL(sl,'#FF4B4B','SL',true,false);drawL(cur,'#F5DFA0','NOW',false,true);
  // Info bar
  ctx.fillStyle='rgba(8,8,9,.96)';ctx.fillRect(0,0,W,44);
  // Gold line under info bar
  const goldGrad=ctx.createLinearGradient(0,0,W,0);
  goldGrad.addColorStop(0,'transparent');goldGrad.addColorStop(.3,'#C9A84C');goldGrad.addColorStop(.7,'#F5DFA0');goldGrad.addColorStop(1,'transparent');
  ctx.fillStyle=goldGrad;ctx.fillRect(0,43,W,1);
  const inP=(dir==='BUY'&&cur>entry)||(dir==='SELL'&&cur<entry);
  const pips=((dir==='BUY'?cur-entry:entry-cur)/p).toFixed(1);
  ctx.fillStyle='#9A9690';ctx.font='bold 12px Inter,sans-serif';ctx.textAlign='left';
  ctx.fillText(inst.replace('_','/')+'  '+dir,pad.l,28);
  ctx.fillStyle=inP?'#22C97A':'#FF4B4B';
  ctx.fillText((inP?'+':'')+pips+' pips',pad.l+175,28);
  ctx.fillStyle='#5A5650';ctx.font='11px Inter,sans-serif';
  ctx.fillText('R:R 1:'+Math.abs((tp-entry)/(sl-entry||.0001)).toFixed(2),pad.l+295,28);
  // Time labels
  const step=Math.floor(candles.length/6);
  ctx.fillStyle='#2E3035';ctx.font='9px JetBrains Mono,monospace';ctx.textAlign='center';
  candles.forEach((c,i)=>{if(i%step===0)ctx.fillText(c.time.slice(11,16),toX(i),H-8);});
}

// Main load
async function loadAll(){
  const btn=$('rbtn');btn.classList.add('loading');
  await Promise.all([loadAccount(),loadStats(),loadRisk(),loadOpen(),loadRecent(),loadInstBreakdown(),updateTicker()]);
  loadEq1();
  btn.classList.remove('loading');
}

setInterval(loadAll,30000);
setInterval(updateTicker,15000);
loadAll();
</script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(content=HTML)
