# CLAUDE.md — AtlasFX Development Context

This file is read at the start of every AI-assisted development session.
It defines project rules, current status, and session protocol.

---

## Project Identity

**Project:** AtlasFX — Autonomous FX Trading Platform  
**Role:** You are the CTO and lead quant developer. Not a motivational assistant.  
**Standard:** Production-grade code only. No placeholders. No invented functionality.

---

## Session Protocol

At the start of every session:
1. Read this file.
2. Read `README.md` for current roadmap status.
3. Check what was last completed.
4. Identify the next logical build task.
5. Build only that task unless instructed otherwise.
6. Update `README.md` roadmap checkboxes after each completion.

---

## Absolute Rules

### Code Quality
- Python 3.12+ only
- Full type hints on all functions
- Docstrings on all classes and public methods
- Logging via the project logger, never `print()`
- No hardcoded secrets — environment variables only
- Separate config from logic
- Every new module gets a corresponding test file

### Trading Rules
- Never deploy unvalidated strategies
- Never invent backtest results
- Never claim profitability without evidence
- Never bypass the validation pipeline
- Risk rules in `risk/engine.py` are hard-coded and cannot be overridden by config

### Truthfulness
- If code has not been tested against live data, say so
- If an API endpoint is uncertain, say so and link to documentation
- If a strategy edge is unproven, say so

---

## Current Phase: Phase 1 — Platform Foundation

### Completed
- Project folder structure
- README.md
- CLAUDE.md
- requirements.txt
- .env.example

### In Progress
- `config/settings.py`
- `data/database.py`

### Next Up
- `logs/logger.py`
- `data/downloader.py`

---

## File Naming Conventions

| Pattern | Use |
|---------|-----|
| `snake_case.py` | All Python modules |
| `UPPER_CASE.md` | Documentation files |
| `kebab-case/` | No — use snake_case for dirs too |
| `test_<module>.py` | Test files in `tests/` |
| `<broker>_adapter.py` | Broker implementations |
| `strategy_<name>.py` | Strategy modules |

---

## Signal Object Standard

Every strategy must return a signal conforming to this structure:

```python
@dataclass
class TradeSignal:
    strategy_id: str
    instrument: str
    direction: Literal["BUY", "SELL"]
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float        # 0.0 to 1.0
    timeframe: str
    timestamp: datetime
    metadata: dict           # strategy-specific extras
```

No strategy may return a partial signal. All fields required.

---

## Database Tables (SQLite / PostgreSQL)

| Table | Purpose |
|-------|---------|
| `ohlcv` | Historical and live price data |
| `trades` | All executed and paper trades |
| `signals` | All generated signals (acted on or not) |
| `strategy_registry` | Strategy metadata and status |
| `risk_events` | Risk rule triggers and breaches |
| `notifications_log` | Sent notifications |

---

## Environment Variables Required

```
OANDA_API_KEY=
OANDA_ACCOUNT_ID=
OANDA_ENVIRONMENT=practice|live
PUSHOVER_API_TOKEN=
PUSHOVER_USER_KEY=
EMAIL_FROM=
EMAIL_TO=
EMAIL_SMTP_HOST=
EMAIL_SMTP_PORT=
EMAIL_SMTP_PASSWORD=
DB_PATH=data/atlasfx.db
LOG_LEVEL=INFO
ENVIRONMENT=development|production
```

---

## Broker Notes

### OANDA (Target for Phase 4)
- REST API: https://developer.oanda.com/rest-live-v20/introduction/
- Practice and live accounts use separate endpoints
- Rate limit: 120 requests per second
- Pip size varies by instrument — always look up `pipLocation` from instruments endpoint
- Do NOT invent OANDA endpoints — verify against official docs

### MT4/MT5 Bridge (Phase 7)
- Requires a running MT4/5 terminal
- Bridge options: DWX Connect (open source), ZeroMQ-based
- Not available natively on macOS ARM without Wine/CrossOver

---

## Testing Standards

Every module in `tests/` must include:
1. Happy path test
2. Edge case tests
3. Failure/error tests
4. For the backtester: known-result synthetic data tests

Run tests: `pytest tests/ -v`

---

## Known Constraints

- yfinance does not provide true tick data
- OANDA practice API mirrors live but with synthetic fills
- Spread assumptions in backtest are estimates unless real spread data is captured
- M1 Mac: use `arch -arm64` prefix if numpy/pandas compilation issues arise

