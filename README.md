# AtlasFX - Autonomous FX Trading System

An algorithmic trading platform running 3 validated strategies across 27 currency pairs on OANDA. Built in Python, deployed on a VPS, monitored via Telegram and a real-time web dashboard.

## Performance (Walk-Forward Validated 2023-2025)

- 2023 in-sample: 997 trades, 66.6% WR, £476 EV/trade
- 2024 validation: 1,384 trades, 68.8% WR, £547 EV/trade  
- 2025 out-of-sample: 1,304 trades, 68.9% WR, £522 EV/trade

24/27 pairs stable across all 3 years. 0 inconsistent pairs. Edge strengthening year-on-year.
Live track record: 87% WR on first 16 live trades.

## Strategies

### London ORB (Opening Range Breakout)
Window: 07:00-14:00 UTC. Asian session forms the range. Price breaks out with momentum, EMA alignment and ADX confirmation. 26 validated pairs. Filters: ADX greater than 25, 200+50 EMA aligned, momentum greater than 0.4xATR, clean break greater than 0.2x range. SL = 0.5x range, TP = pair-specific.

### NY ORB (New York Opening Range Breakout)
Window: 14:00-17:00 UTC. 13:00 UTC hour forms the NY range. Breakout on session open with trend alignment. 23 validated pairs. Filters: ADX greater than 25, 200 EMA aligned, momentum greater than 0.5xATR. SL = 0.5x range, TP = pair-specific.

### EMA Pullback
Window: 07:00-16:00 UTC. Full EMA stack aligned (21/50/200), price pulls back to 21 EMA and bounces with RSI confirmation. 23 pairs including XAU/USD and XAG/USD. Filters: ADX greater than 35, RSI 45-68 BUY / 32-55 SELL. SL = 1.0xATR, TP = 2.5x pullback.

## Architecture

VPS (Ubuntu 24) runs the trading agent 24/5 with SQLite database as source of truth.
Mac runs the dashboard locally at localhost:8420, syncing from VPS every 60 seconds via SCP.

## Tech Stack

Python 3.12, OANDA REST API v20, SQLite WAL mode, FastAPI, APScheduler, pandas, numpy, Telegram Bot API, Claude AI, systemd on Ubuntu 24.

## Project Structure

strategies/ - London ORB, NY ORB, EMA Pullback + pair_config.py with optimal TP targets
paper_trading/agent.py - Main trading agent
broker/oanda.py - OANDA API client
risk/engine.py - Risk management (1% per trade, 2% daily DD limit)
execution/engine.py - Order execution
filters/ - Correlation filter, news filter, regime detector
telegram/bot.py - AI-powered Telegram bot with natural language
dashboard/ - FastAPI backend + real-time HTML dashboard
monitoring/health_check.py - Self-diagnostic system (runs at 07:00, 10:00, 13:00, 16:00 UTC)
journal/trade_journal.py - Trade recording
backtesting/ - Master backtest + walk-forward validation scripts
data/database.py - SQLAlchemy models
config/settings.py - Configuration
scripts/ - run_agent.py, run_all.py, run_dashboard.py

## Setup

### Prerequisites
Python 3.12+, OANDA account, VPS Ubuntu 24, Telegram bot token (optional), Anthropic API key (optional)

### Installation

git clone https://github.com/clearcosmeticss/AtlasFX.git
cd AtlasFX
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your credentials

### Environment Variables (.env)

OANDA_API_KEY=your_oanda_api_key
OANDA_ACCOUNT_ID=your_account_id
OANDA_ENVIRONMENT=practice
RISK_PER_TRADE_PCT=1.0
LOG_LEVEL=INFO
ENVIRONMENT=production
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
ANTHROPIC_API_KEY=your_key

### Running Locally

python scripts/run_dashboard.py   # Dashboard only at localhost:8420
python scripts/run_agent.py       # Trading agent only
python scripts/run_all.py         # Everything

### VPS Deployment (Ubuntu 24)

git clone https://github.com/clearcosmeticss/AtlasFX.git /opt/atlasfx
cd /opt/atlasfx
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env

Create /etc/systemd/system/atlasfx.service:

[Unit]
Description=AtlasFX Autonomous Trading Agent
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/atlasfx
Environment=PATH=/opt/atlasfx/venv/bin
ExecStart=/opt/atlasfx/venv/bin/python scripts/run_agent.py
Restart=always
RestartSec=30
StandardOutput=append:/opt/atlasfx/logs/atlasfx.log
StandardError=append:/opt/atlasfx/logs/atlasfx.log

[Install]
WantedBy=multi-user.target

Then: systemctl enable atlasfx && systemctl start atlasfx

### Running Backtests

Download M1 data from histdata.com and place zip files in ~/Desktop/Backtesting data/

python backtesting/run_backtest.py    # Full backtest all pairs
python backtesting/walk_forward.py    # Walk-forward validation

## Risk Management

Risk per trade: 1.0% practice / 0.5% funded accounts
Daily drawdown limit: 2.0%
Weekly drawdown limit: 5.0%
Max open positions: 6
Max per correlated group: 2
Min R:R: 1.2
No trading days: Monday and Friday

## Telegram Bot Commands

/status - Account balance, NAV, open positions
/trades - Last 8 closed trades
/daily - Today P&L report
/pairs - All active pairs per strategy
/close GBPUSD - Close a specific position
/pause - Pause new signals
/resume - Resume trading
/health - Full system diagnostic
Natural language - Ask anything, AI powered via Claude

## Top Performing Pairs (EV per trade at 1% risk, £100K account)

GBP/AUD EMA Pullback: 75.0% WR, £1,625 EV
CAD/JPY EMA Pullback: 72.4% WR, £1,534 EV
CHF/JPY EMA Pullback: 66.7% WR, £1,333 EV
GBP/CAD EMA Pullback: 66.7% WR, £1,333 EV
USD/CHF EMA Pullback: 65.5% WR, £1,293 EV
NZD/USD EMA Pullback: 65.2% WR, £1,283 EV
XAU/USD EMA Pullback: 65.0% WR, £1,275 EV
XAG/USD NY ORB: 77.4% WR, £935 EV
NZD/USD NY ORB: 76.0% WR, £900 EV
EUR/USD NY ORB: 68.1% WR, £702 EV

## Walk-Forward Summary

The walk-forward test splits data into training (2023), validation (2024) and out-of-sample (2025) periods. Parameters are fixed - no reoptimisation between periods. Results:

STABLE pairs (24/27): AUDCAD, AUDCHF, AUDUSD, CADJPY, CHFJPY, EURAUD, EURCAD, EURGBP, EURJPY, EURNZD, EURUSD, GBPAUD, GBPCAD, GBPCHF, GBPNZD, GBPUSD, NZDCAD, NZDJPY, NZDUSD, USDCAD, USDCHF, USDJPY, XAGUSD, XAUUSD

VOLATILE but profitable (3/27): AUDNZD, GBPJPY, NZDCHF

INCONSISTENT (0/27): None

## Disclaimer

This system trades real capital. Algorithmic trading carries significant risk of loss. Past backtested performance does not guarantee future results. The walk-forward validation reduces but does not eliminate overfitting risk. Always use appropriate risk management and only trade capital you can afford to lose.

Built by Thomas Flynn - AtlasFX v1.0
