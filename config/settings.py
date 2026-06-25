"""
config/settings.py
──────────────────
Central configuration for AtlasFX.

Loads from environment variables (via .env) using pydantic-settings.
All application code should import settings from here — never read
os.environ directly in other modules.

Usage:
    from config.settings import settings
    print(settings.oanda_environment)
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    """Runtime environment."""
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class LogLevel(str, Enum):
    """Logging verbosity."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class OandaEnvironment(str, Enum):
    """OANDA API environment."""
    PRACTICE = "practice"
    LIVE = "live"


# ── Base paths ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """
    AtlasFX application settings.

    All values are loaded from environment variables.
    In development, .env is loaded automatically by pydantic-settings.
    In production, environment variables should be injected by the container.
    """

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Runtime ───────────────────────────────────────────────
    environment: Environment = Environment.DEVELOPMENT
    log_level: LogLevel = LogLevel.INFO

    # ── Database ──────────────────────────────────────────────
    db_path: Path = PROJECT_ROOT / "data" / "atlasfx.db"
    database_url: Optional[str] = None  # PostgreSQL for production

    @field_validator("db_path", mode="before")
    @classmethod
    def resolve_db_path(cls, v: str | Path) -> Path:
        """Resolve relative paths against project root."""
        p = Path(v)
        if not p.is_absolute():
            return PROJECT_ROOT / p
        return p

    # ── OANDA Broker ──────────────────────────────────────────
    oanda_api_key: Optional[str] = None
    oanda_account_id: Optional[str] = None
    oanda_environment: OandaEnvironment = OandaEnvironment.PRACTICE

    @property
    def oanda_base_url(self) -> str:
        """Returns the correct OANDA REST API base URL."""
        if self.oanda_environment == OandaEnvironment.LIVE:
            return "https://api-fxtrade.oanda.com"
        return "https://api-fxpractice.oanda.com"

    @property
    def oanda_stream_url(self) -> str:
        """Returns the correct OANDA streaming URL."""
        if self.oanda_environment == OandaEnvironment.LIVE:
            return "https://stream-fxtrade.oanda.com"
        return "https://stream-fxpractice.oanda.com"

    # ── Notifications ─────────────────────────────────────────
    pushover_api_token: Optional[str] = None
    pushover_user_key: Optional[str] = None

    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    anthropic_api_key: Optional[str] = None

    email_enabled: bool = False
    email_from: Optional[str] = None
    email_to: Optional[str] = None
    email_smtp_host: str = "smtp.gmail.com"
    email_smtp_port: int = 587
    email_smtp_password: Optional[str] = None

    # ── Risk Parameters ───────────────────────────────────────
    # These are defaults. The risk engine enforces hard limits
    # regardless of these values.
    risk_per_trade_pct: float = Field(default=1.0, ge=0.01, le=1.0)
    max_daily_drawdown_pct: float = Field(default=2.0, ge=0.1, le=10.0)
    max_weekly_drawdown_pct: float = Field(default=5.0, ge=0.5, le=20.0)
    max_concurrent_exposure_pct: float = Field(default=2.0, ge=0.5, le=10.0)

    # ── Dashboard ─────────────────────────────────────────────
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8420
    dashboard_secret_key: str = "change-this-in-production"

    # ── Data paths ────────────────────────────────────────────
    data_historical_path: Path = PROJECT_ROOT / "data" / "historical"
    data_live_path: Path = PROJECT_ROOT / "data" / "live"
    data_news_path: Path = PROJECT_ROOT / "data" / "news"

    @field_validator("data_historical_path", "data_live_path", "data_news_path", mode="before")
    @classmethod
    def resolve_data_paths(cls, v: str | Path) -> Path:
        p = Path(v)
        if not p.is_absolute():
            return PROJECT_ROOT / p
        return p

    # ── Safety guards ─────────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    @property
    def is_live_trading_enabled(self) -> bool:
        """
        Live trading requires both production environment AND
        explicit OANDA live credentials. Safety gate.
        """
        return (
            self.is_production
            and self.oanda_environment == OandaEnvironment.LIVE
            and self.oanda_api_key is not None
            and self.oanda_account_id is not None
        )

    def assert_live_trading_safe(self) -> None:
        """
        Raises RuntimeError if live trading preconditions are not met.
        Called by the execution engine before any live order submission.
        """
        if not self.oanda_api_key:
            raise RuntimeError("OANDA_API_KEY not set. Cannot trade live.")
        if not self.oanda_account_id:
            raise RuntimeError("OANDA_ACCOUNT_ID not set. Cannot trade live.")
        if self.environment != Environment.PRODUCTION:
            raise RuntimeError(
                "Live trading requires ENVIRONMENT=production. "
                "Current environment: development."
            )
        if self.oanda_environment != OandaEnvironment.LIVE:
            raise RuntimeError(
                "OANDA_ENVIRONMENT must be 'live' for live trading. "
                f"Current: {self.oanda_environment.value}"
            )


# ── Instrument Configuration ──────────────────────────────────────────────────

INSTRUMENTS = {
    "EUR_USD": {
        "display": "EUR/USD",
        "pip_location": -4,         # 0.0001 per pip
        "min_trade_units": 1,
        "typical_spread_pips": 0.8,
        "session": ["london", "new_york"],
    },
    "GBP_USD": {
        "display": "GBP/USD",
        "pip_location": -4,
        "min_trade_units": 1,
        "typical_spread_pips": 1.2,
        "session": ["london", "new_york"],
    },
    "USD_JPY": {
        "display": "USD/JPY",
        "pip_location": -2,         # 0.01 per pip
        "min_trade_units": 1,
        "typical_spread_pips": 0.9,
        "session": ["tokyo", "london", "new_york"],
    },
    "AUD_USD": {
        "display": "AUD/USD",
        "pip_location": -4,
        "min_trade_units": 1,
        "typical_spread_pips": 1.0,
        "session": ["sydney", "london"],
    },
    "XAU_USD": {
        "display": "XAU/USD (Gold)",
        "pip_location": -2,         # $0.01 per pip on gold
        "min_trade_units": 1,
        "typical_spread_pips": 15,
        "session": ["london", "new_york"],
    },
}

TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D"]

TRADING_SESSIONS = {
    "sydney":   {"open": "22:00", "close": "07:00"},  # UTC
    "tokyo":    {"open": "00:00", "close": "09:00"},
    "london":   {"open": "07:00", "close": "16:00"},
    "new_york": {"open": "12:00", "close": "21:00"},
}


# ── Module-level singleton ────────────────────────────────────────────────────

settings = Settings()
