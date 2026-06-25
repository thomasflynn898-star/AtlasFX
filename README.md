# AtlasFX — Autonomous FX Trading Platform

> **Version:** 0.1.0 — Architecture & Scaffold  
> **Status:** Phase 1 In Progress  
> **Last Updated:** 2026-06-10  
> **Environment:** MacBook Air M1 (dev) → Linux VPS (prod)

---

## What AtlasFX Is

AtlasFX is a modular, production-grade foreign exchange research and execution platform.
It is not a trading advisory tool. It is a systematic trading system built to research,
validate, and autonomously execute rule-based FX strategies.

Every strategy must pass a mandatory validation pipeline before live capital is risked.
Capital preservation takes priority over performance at every stage.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        AtlasFX Platform                      │
├──────────────┬──────────────┬──────────────┬────────────────┤
│  Data Engine │ Strategy Eng │  Risk Engine │ Execution Eng  │
│              │              │              │                │
│  Historical  │  ICT/SMC     │  Position    │  Broker Layer  │
│  Live Feed   │  Breakout    │  Sizing      │  Order Mgmt    │
│  News Filter │  Trend       │  Drawdown    │  Fill Monitor  │
│  Cache/DB    │  Mean Rev    │  Exposure    │  Error Recov   │
├──────────────┴──────────────┴──────────────┴────────────────┤
│                    Backtesting Engine                        │
│   Walk-Forward | Out-of-Sample | Monte Carlo | Sensitivity  │
├──────────────┬──────────────┬──────────────┬────────────────┤
│  Paper Trade │   Journal    │  Analytics   │  Dashboard     │
│  Engine      │  & Logging   │  & Reports   │  (FastAPI)     │
├──────────────┴──────────────┴──────────────┴────────────────┤
│              Notifications (Push / Email)                    │
└─────────────────────────────────────────────────────────────┘
```

---

## Mandatory Strategy Validation Pipeline

No strategy may be deployed to live trading without completing every stage:

```
1. Research          → Document the hypothesis and edge
2. Rule Definition   → Explicit, unambiguous entry/exit rules
3. Implementation    → Python module with full type hints
4. Historical Test   → Minimum 3 years, multiple pairs
5. Walk-Forward      → Rolling window out-of-sample validation
6. Monte Carlo       → 10,000+ resampled equity curves
7. Paper Trading     → Minimum 4 weeks live paper
8. Small Live        → 0.1% risk, minimum 20 trades
9. Production        → Full risk allocation
```

If any stage produces unacceptable metrics, the strategy is halted and documented.

---

## Risk Rules (Hard-Coded, Never Overridden)

| Rule | Value |
|------|-------|
| Default risk per trade | 0.5% of account equity |
| Maximum risk per trade | 1.0% |
| Maximum daily drawdown | 2.0% |
| Maximum weekly drawdown | 5.0% |
| Maximum concurrent exposure | 2.0% total |
| Martingale | Prohibited |
| Averaging down | Prohibited |
| Risk adjustment after wins/losses | Prohibited |

---

## Development Roadmap

### Phase 1 — Platform Foundation (Current)
- [x] Project structure and scaffold
- [x] README and CLAUDE.md
- [x] requirements.txt
- [x] .env template
- [ ] Config system (`config/settings.py`)
- [ ] Database schema and init (`data/database.py`)
- [ ] Logging system (`logs/logger.py`)
- [ ] Data engine — historical downloader
- [ ] Data engine — live feed handler
- [ ] Data engine — cache and storage layer

### Phase 2 — Research & Backtesting Infrastructure
- [ ] Strategy base class (`strategies/base.py`)
- [ ] Indicator library (`indicators/`)
- [ ] Backtesting engine (`backtesting/engine.py`)
- [ ] Walk-forward validation (`backtesting/walk_forward.py`)
- [ ] Monte Carlo module (`backtesting/monte_carlo.py`)
- [ ] Performance analytics (`analytics/performance.py`)

### Phase 3 — Strategy Implementation
- [ ] ICT Silver Bullet (SMC)
- [ ] London Breakout
- [ ] MACD + EMA Trend
- [ ] Multi-TF Confluence

### Phase 4 — Execution Infrastructure
- [ ] Risk engine (`risk/engine.py`)
- [ ] Position sizer (`risk/position_sizer.py`)
- [ ] Broker abstraction layer (`broker/base.py`)
- [ ] OANDA broker adapter (`broker/oanda.py`)
- [ ] Execution engine (`execution/engine.py`)
- [ ] Order manager (`execution/order_manager.py`)

### Phase 5 — Autonomous Operation
- [ ] Paper trading engine (`paper_trading/engine.py`)
- [ ] Trading agent service (`live_trading/agent.py`)
- [ ] Journal and logging (`journal/`)
- [ ] Notification engine (`notifications/`)

### Phase 6 — Dashboard & Reports
- [ ] FastAPI dashboard backend (`dashboard/api.py`)
- [ ] Dashboard frontend (HTML/JS)
- [ ] Daily/weekly/monthly reports
- [ ] Mobile-friendly report format

### Phase 7 — Production Hardening
- [ ] Docker containers
- [ ] VPS deployment scripts
- [ ] Health monitoring
- [ ] Automatic restart
- [ ] PostgreSQL migration (optional)

---

## Module Responsibilities

| Module | Responsibility |
|--------|---------------|
| `config/` | All settings, environment loading, instrument lists |
| `data/` | Historical download, live feed, caching, DB writes |
| `strategies/` | One file per strategy, all return standard signal objects |
| `indicators/` | Pure functions: MA, ATR, RSI, Bollinger, FVG detection |
| `backtesting/` | Event-driven backtest engine, walk-forward, Monte Carlo |
| `paper_trading/` | Real-time paper execution against live prices |
| `live_trading/` | Autonomous agent, signal loop, position monitoring |
| `execution/` | Order submission, fill tracking, modification, closure |
| `risk/` | Position sizing, drawdown monitoring, exposure limits |
| `broker/` | Broker abstraction — OANDA, MT4, others pluggable |
| `journal/` | Trade logging, SQLite writes, trade tagging |
| `analytics/` | Performance stats, Sharpe, drawdown, profit factor |
| `dashboard/` | FastAPI server, HTML dashboard, mobile reports |
| `notifications/` | Push (Pushover/Telegram), email (SMTP) |
| `logs/` | Structured logging, daily rotation, error tracking |
| `tests/` | Unit and integration tests per module |
| `scripts/` | CLI utilities: download data, run backtest, etc. |

---

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12+ |
| Database | SQLite (dev), PostgreSQL (prod) |
| Data | yfinance, OANDA REST API |
| Async | asyncio, aiohttp |
| Scheduling | APScheduler |
| Dashboard | FastAPI + Jinja2 |
| Charting | Plotly |
| Notifications | Pushover, smtplib |
| Deployment | Docker, docker-compose |
| Testing | pytest |

---

## Installation

See `scripts/install.sh` for automated setup.

Manual:
```bash
cd AtlasFX
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your broker credentials
python scripts/init_db.py
```

---

## Important: What This System Does Not Do

- It does not guarantee profitable trading
- It does not remove the need for strategy validation
- It does not override risk rules under any circumstances
- It does not deploy unvalidated strategies
- Backtest results are not predictive of live performance

---

## Broker Support

| Broker | Status | Notes |
|--------|--------|-------|
| OANDA | Planned Phase 4 | REST API, well-documented |
| Interactive Brokers | Planned Phase 7 | TWS API |
| MT4/MT5 (via bridge) | Planned Phase 7 | Requires local bridge |

