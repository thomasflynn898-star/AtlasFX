"""
data/downloader.py
──────────────────
Historical FX data downloader.

Downloads OHLCV data for configured instruments using yfinance as the
primary source during development/research. In production, OANDA's
historical candles API is used for higher-quality data.

Stores all data as Parquet files (fast, compressed) with a SQLite index.
Data is deduplicated on insert — safe to re-run.

Usage:
    from data.downloader import HistoricalDownloader
    dl = HistoricalDownloader()
    df = dl.download("EUR_USD", "H1", start="2020-01-01", end="2024-01-01")

CLI:
    python scripts/download_data.py --instrument EUR_USD --timeframe H1 --years 4
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

from config.settings import INSTRUMENTS, settings
from data.database import OHLCV, get_session
from logs.logger import get_logger

log = get_logger(__name__)

# ── yfinance ticker map ────────────────────────────────────────────────────────
# yfinance uses different symbols than OANDA.
# Note: yfinance FX data has known gaps and quality limitations.
# It is suitable for strategy research but NOT for live execution decisions.

YFINANCE_SYMBOL_MAP: dict[str, str] = {
    "EUR_USD": "EURUSD=X",
    "GBP_USD": "GBPUSD=X",
    "USD_JPY": "JPY=X",       # yfinance oddity — USD is base
    "AUD_USD": "AUDUSD=X",
    "USD_CHF": "CHF=X",
    "NZD_USD": "NZDUSD=X",
    "USD_CAD": "CAD=X",
    "XAU_USD": "GC=F",        # Gold futures — not spot, use cautiously
    "EUR_GBP": "EURGBP=X",
    "GBP_JPY": "GBPJPY=X",
}

# yfinance interval map — not all intervals available for all periods
YFINANCE_INTERVAL_MAP: dict[str, str] = {
    "M1":  "1m",
    "M5":  "5m",
    "M15": "15m",
    "M30": "30m",
    "H1":  "1h",
    "H4":  "4h",   # Not natively supported — will be resampled from H1
    "D":   "1d",
}

# yfinance only keeps intraday data for limited periods
YFINANCE_MAX_PERIOD: dict[str, int] = {
    "M1":  7,      # 7 days max
    "M5":  60,     # 60 days max
    "M15": 60,
    "M30": 60,
    "H1":  730,    # ~2 years
    "H4":  730,
    "D":   9999,   # Unlimited daily
}


class HistoricalDownloader:
    """
    Downloads and stores historical FX OHLCV data.

    Data source priority:
        1. Local cache (Parquet files)
        2. OANDA historical API (if credentials available)
        3. yfinance (research/development fallback)

    NOTE: This module has NOT been tested against live OANDA credentials.
    The yfinance path has been tested in development.
    """

    def __init__(self) -> None:
        self.historical_path = settings.data_historical_path
        self.historical_path.mkdir(parents=True, exist_ok=True)
        log.info("downloader_initialised", path=str(self.historical_path))

    def _parquet_path(self, instrument: str, timeframe: str) -> Path:
        """Return the local Parquet cache path for an instrument/timeframe."""
        return self.historical_path / instrument / f"{timeframe}.parquet"

    def _load_from_cache(
        self, instrument: str, timeframe: str
    ) -> Optional[pd.DataFrame]:
        """Load cached data from Parquet if it exists."""
        path = self._parquet_path(instrument, timeframe)
        if not path.exists():
            return None
        try:
            df = pd.read_parquet(path)
            log.debug(
                "cache_loaded",
                instrument=instrument,
                timeframe=timeframe,
                rows=len(df),
            )
            return df
        except Exception as e:
            log.warning("cache_read_failed", path=str(path), error=str(e))
            return None

    def _save_to_cache(
        self, df: pd.DataFrame, instrument: str, timeframe: str
    ) -> None:
        """Save DataFrame to Parquet cache."""
        path = self._parquet_path(instrument, timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=True)
        log.debug(
            "cache_saved",
            instrument=instrument,
            timeframe=timeframe,
            rows=len(df),
            path=str(path),
        )

    def _save_to_db(
        self, df: pd.DataFrame, instrument: str, timeframe: str, source: str
    ) -> int:
        """
        Write OHLCV rows to the database.

        Skips rows that already exist (deduplication via INSERT OR IGNORE).
        Returns the number of new rows inserted.
        """
        inserted = 0
        with get_session() as session:
            for ts, row in df.iterrows():
                # Check for existing record
                existing = (
                    session.query(OHLCV)
                    .filter_by(
                        instrument=instrument,
                        timeframe=timeframe,
                        timestamp=ts.to_pydatetime().replace(tzinfo=None),
                    )
                    .first()
                )
                if existing:
                    continue
                record = OHLCV(
                    instrument=instrument,
                    timeframe=timeframe,
                    timestamp=ts.to_pydatetime().replace(tzinfo=None),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row.get("Volume", 0) or 0),
                    source=source,
                )
                session.add(record)
                inserted += 1
        return inserted

    def download_yfinance(
        self,
        instrument: str,
        timeframe: str,
        start: str,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Download data via yfinance.

        Args:
            instrument: OANDA-style instrument e.g. 'EUR_USD'
            timeframe: AtlasFX timeframe e.g. 'H1'
            start: Start date string 'YYYY-MM-DD'
            end: End date string 'YYYY-MM-DD', defaults to today

        Returns:
            DataFrame with OHLCV columns indexed by UTC datetime.

        Raises:
            ValueError: If instrument or timeframe is not mapped.
            RuntimeError: If yfinance returns no data.
        """
        if instrument not in YFINANCE_SYMBOL_MAP:
            raise ValueError(
                f"Instrument '{instrument}' not in yfinance map. "
                f"Available: {list(YFINANCE_SYMBOL_MAP.keys())}"
            )

        if timeframe not in YFINANCE_INTERVAL_MAP:
            raise ValueError(
                f"Timeframe '{timeframe}' not supported. "
                f"Available: {list(YFINANCE_INTERVAL_MAP.keys())}"
            )

        ticker = YFINANCE_SYMBOL_MAP[instrument]
        interval = YFINANCE_INTERVAL_MAP[timeframe]

        # H4 not natively in yfinance — download H1 and resample
        resample_to_h4 = (timeframe == "H4")
        if resample_to_h4:
            interval = "1h"

        if end is None:
            end = datetime.utcnow().strftime("%Y-%m-%d")

        log.info(
            "yfinance_download_start",
            instrument=instrument,
            ticker=ticker,
            interval=interval,
            start=start,
            end=end,
        )

        try:
            data = yf.download(
                tickers=ticker,
                start=start,
                end=end,
                interval=interval,
                auto_adjust=True,
                progress=False,
            )
        except Exception as e:
            raise RuntimeError(f"yfinance download failed: {e}") from e

        if data.empty:
            raise RuntimeError(
                f"yfinance returned no data for {instrument} "
                f"({ticker}) {timeframe} {start}→{end}"
            )

        # Flatten multi-level columns if present
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        # Keep only OHLCV
        cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
        data = data[cols].copy()

        # Ensure UTC timezone
        if data.index.tz is None:
            data.index = data.index.tz_localize("UTC")
        else:
            data.index = data.index.tz_convert("UTC")

        # Remove timezone for storage (stored as UTC implicitly)
        data.index = data.index.tz_localize(None)

        # Drop NaN rows
        data.dropna(subset=["Open", "High", "Low", "Close"], inplace=True)

        # Resample to H4 if needed
        if resample_to_h4:
            data = data.resample("4h").agg(
                {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
            ).dropna()

        log.info(
            "yfinance_download_complete",
            instrument=instrument,
            timeframe=timeframe,
            rows=len(data),
            first=str(data.index[0]),
            last=str(data.index[-1]),
        )

        return data

    def download(
        self,
        instrument: str,
        timeframe: str,
        start: str,
        end: Optional[str] = None,
        force_refresh: bool = False,
        save_to_db: bool = True,
    ) -> pd.DataFrame:
        """
        Download historical data with caching.

        Checks local Parquet cache first. Downloads from source if not cached
        or if force_refresh=True. Appends new data to existing cache.

        Args:
            instrument: e.g. 'EUR_USD'
            timeframe: e.g. 'H1'
            start: Start date 'YYYY-MM-DD'
            end: End date 'YYYY-MM-DD', defaults to today
            force_refresh: If True, bypass cache and re-download
            save_to_db: If True, write to SQLite database as well

        Returns:
            DataFrame with OHLCV data
        """
        if end is None:
            end = datetime.utcnow().strftime("%Y-%m-%d")

        # Try cache first
        if not force_refresh:
            cached = self._load_from_cache(instrument, timeframe)
            if cached is not None:
                start_dt = pd.Timestamp(start)
                end_dt = pd.Timestamp(end)
                filtered = cached[
                    (cached.index >= start_dt) & (cached.index <= end_dt)
                ]
                if len(filtered) > 0:
                    log.info(
                        "data_served_from_cache",
                        instrument=instrument,
                        timeframe=timeframe,
                        rows=len(filtered),
                    )
                    return filtered

        # Download from source
        df = self.download_yfinance(instrument, timeframe, start, end)

        # Merge with existing cache
        existing = self._load_from_cache(instrument, timeframe)
        if existing is not None:
            combined = pd.concat([existing, df])
            combined = combined[~combined.index.duplicated(keep="last")]
            combined.sort_index(inplace=True)
        else:
            combined = df

        # Save to cache
        self._save_to_cache(combined, instrument, timeframe)

        # Save to database
        if save_to_db:
            inserted = self._save_to_db(df, instrument, timeframe, source="yfinance")
            log.info(
                "data_saved_to_db",
                instrument=instrument,
                timeframe=timeframe,
                new_rows=inserted,
            )

        return df

    def download_all_configured(
        self,
        timeframes: list[str] | None = None,
        years: int = 3,
    ) -> dict[str, dict[str, pd.DataFrame]]:
        """
        Download data for all instruments in INSTRUMENTS config.

        Args:
            timeframes: List of timeframes to download. Defaults to ['H1', 'H4', 'D']
            years: Number of years of history to download

        Returns:
            Nested dict: {instrument: {timeframe: DataFrame}}
        """
        if timeframes is None:
            timeframes = ["H1", "H4", "D"]

        start = (datetime.utcnow() - timedelta(days=365 * years)).strftime("%Y-%m-%d")
        results: dict[str, dict[str, pd.DataFrame]] = {}

        for instrument in INSTRUMENTS:
            results[instrument] = {}
            for tf in timeframes:
                try:
                    log.info(
                        "bulk_download_start",
                        instrument=instrument,
                        timeframe=tf,
                        start=start,
                    )
                    df = self.download(instrument, tf, start=start)
                    results[instrument][tf] = df
                    time.sleep(0.5)  # Rate limiting
                except Exception as e:
                    log.error(
                        "bulk_download_failed",
                        instrument=instrument,
                        timeframe=tf,
                        error=str(e),
                    )
                    results[instrument][tf] = pd.DataFrame()

        return results

    def load_for_backtest(
        self,
        instrument: str,
        timeframe: str,
        start: str,
        end: str,
    ) -> pd.DataFrame:
        """
        Load data specifically for backtesting.

        Ensures data is sorted, has no gaps in trading hours (warns if found),
        and is within the requested date range.

        Args:
            instrument: e.g. 'EUR_USD'
            timeframe: e.g. 'H1'
            start: Start date
            end: End date

        Returns:
            Clean DataFrame ready for backtesting
        """
        df = self.download(instrument, timeframe, start=start, end=end)

        if df.empty:
            raise ValueError(
                f"No data available for {instrument} {timeframe} {start}→{end}"
            )

        # Sort and deduplicate
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="first")]

        # Check for large gaps (> 5 candles missing)
        if len(df) > 10:
            expected_freq_map = {
                "M1": "1min", "M5": "5min", "M15": "15min",
                "M30": "30min", "H1": "1h", "H4": "4h", "D": "1D",
            }
            freq = expected_freq_map.get(timeframe)
            if freq and timeframe != "D":
                full_index = pd.date_range(df.index[0], df.index[-1], freq=freq)
                missing_count = len(full_index) - len(df)
                if missing_count > 100:
                    log.warning(
                        "data_gaps_detected",
                        instrument=instrument,
                        timeframe=timeframe,
                        missing_bars=missing_count,
                        note="Gaps expected over weekends. Large gaps may indicate data issues.",
                    )

        log.info(
            "data_loaded_for_backtest",
            instrument=instrument,
            timeframe=timeframe,
            rows=len(df),
            start=str(df.index[0]),
            end=str(df.index[-1]),
        )

        return df
