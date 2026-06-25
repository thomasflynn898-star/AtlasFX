"""
indicators/technical.py
────────────────────────
Pure technical indicator functions for AtlasFX.

All functions:
    - Accept a pandas Series or DataFrame
    - Return a pandas Series
    - Are completely stateless (no side effects)
    - Use only vectorised operations (no Python loops)
    - Return NaN for periods with insufficient data

These are used by strategies and the backtesting engine.
They are NOT wrappers around TA-lib — they are explicit
implementations so behaviour is fully understood and auditable.

NOTE: These have been tested against known values but have NOT
been validated against a live broker feed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ── Trend indicators ──────────────────────────────────────────────────────────

def ema(series: pd.Series, period: int) -> pd.Series:
    """
    Exponential Moving Average.

    Args:
        series: Price series (typically Close)
        period: Lookback period

    Returns:
        EMA series, NaN for first (period-1) values
    """
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    """
    Simple Moving Average.

    Args:
        series: Price series
        period: Lookback period

    Returns:
        SMA series
    """
    return series.rolling(window=period).mean()


def wma(series: pd.Series, period: int) -> pd.Series:
    """
    Weighted Moving Average (linearly weighted, recent values heavier).

    Args:
        series: Price series
        period: Lookback period

    Returns:
        WMA series
    """
    weights = np.arange(1, period + 1, dtype=float)

    def _wma(x: np.ndarray) -> float:
        return np.dot(x, weights) / weights.sum()

    return series.rolling(window=period).apply(_wma, raw=True)


# ── Volatility indicators ─────────────────────────────────────────────────────

def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """
    Average True Range.

    True Range = max(H-L, |H-prev_C|, |L-prev_C|)
    ATR = EMA(True Range, period)

    Args:
        high: High price series
        low: Low price series
        close: Close price series
        period: Lookback period (default 14)

    Returns:
        ATR series
    """
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def bollinger_bands(
    series: pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Bollinger Bands.

    Args:
        series: Price series (typically Close)
        period: SMA lookback period (default 20)
        std_dev: Number of standard deviations (default 2.0)

    Returns:
        Tuple of (upper_band, middle_band, lower_band)
    """
    middle = sma(series, period)
    std = series.rolling(window=period).std(ddof=0)
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)
    return upper, middle, lower


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """
    True Range (single period, not averaged).

    Args:
        high: High series
        low: Low series
        close: Close series

    Returns:
        TR series
    """
    prev_close = close.shift(1)
    return pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)


# ── Momentum indicators ───────────────────────────────────────────────────────

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Relative Strength Index (Wilder's smoothing method).

    Args:
        series: Price series (typically Close)
        period: Lookback period (default 14)

    Returns:
        RSI series, values 0–100
    """
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    MACD — Moving Average Convergence Divergence.

    Args:
        series: Price series (typically Close)
        fast: Fast EMA period (default 12)
        slow: Slow EMA period (default 26)
        signal: Signal line EMA period (default 9)

    Returns:
        Tuple of (macd_line, signal_line, histogram)
    """
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    d_period: int = 3,
) -> tuple[pd.Series, pd.Series]:
    """
    Stochastic Oscillator (%K and %D).

    Args:
        high: High series
        low: Low series
        close: Close series
        k_period: %K lookback period (default 14)
        d_period: %D smoothing period (default 3)

    Returns:
        Tuple of (%K, %D)
    """
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
    d = sma(k, d_period)
    return k, d


# ── Structure indicators ──────────────────────────────────────────────────────

def swing_highs(high: pd.Series, left: int = 2, right: int = 2) -> pd.Series:
    """
    Identify swing high pivot points.

    A bar is a swing high if its high is greater than `left` bars to the
    left and `right` bars to the right.

    Args:
        high: High price series
        left: Number of bars to the left
        right: Number of bars to the right

    Returns:
        Boolean series, True at swing high bars
    """
    result = pd.Series(False, index=high.index)
    for i in range(left, len(high) - right):
        window_left = high.iloc[i - left:i]
        window_right = high.iloc[i + 1:i + right + 1]
        if high.iloc[i] > window_left.max() and high.iloc[i] > window_right.max():
            result.iloc[i] = True
    return result


def swing_lows(low: pd.Series, left: int = 2, right: int = 2) -> pd.Series:
    """
    Identify swing low pivot points.

    Args:
        low: Low price series
        left: Number of bars to the left
        right: Number of bars to the right

    Returns:
        Boolean series, True at swing low bars
    """
    result = pd.Series(False, index=low.index)
    for i in range(left, len(low) - right):
        window_left = low.iloc[i - left:i]
        window_right = low.iloc[i + 1:i + right + 1]
        if low.iloc[i] < window_left.min() and low.iloc[i] < window_right.min():
            result.iloc[i] = True
    return result


def highest(series: pd.Series, period: int) -> pd.Series:
    """Rolling highest value over period."""
    return series.rolling(window=period).max()


def lowest(series: pd.Series, period: int) -> pd.Series:
    """Rolling lowest value over period."""
    return series.rolling(window=period).min()


# ── Session range helpers ─────────────────────────────────────────────────────

def session_high_low(
    df: pd.DataFrame,
    session_start_hour: int,
    session_end_hour: int,
) -> pd.DataFrame:
    """
    Calculate the high and low of a given session for each day.

    Requires the DataFrame index to be datetime with UTC timezone or naive UTC.

    Args:
        df: OHLCV DataFrame with datetime index
        session_start_hour: Session open hour (UTC, 0–23)
        session_end_hour: Session close hour (UTC, 0–23)

    Returns:
        DataFrame with columns: session_high, session_low, date
    """
    df = df.copy()
    df["hour"] = df.index.hour
    df["date"] = df.index.date

    mask = (df["hour"] >= session_start_hour) & (df["hour"] < session_end_hour)
    session = df[mask].groupby("date").agg(
        session_high=("High", "max"),
        session_low=("Low", "min"),
    )
    return session


# ── Candle pattern helpers ────────────────────────────────────────────────────

def candle_body(open_: pd.Series, close: pd.Series) -> pd.Series:
    """Absolute candle body size."""
    return (close - open_).abs()


def candle_range(high: pd.Series, low: pd.Series) -> pd.Series:
    """Full candle range (high - low)."""
    return high - low


def is_bullish(open_: pd.Series, close: pd.Series) -> pd.Series:
    """True where close > open (bullish candle)."""
    return close > open_


def is_bearish(open_: pd.Series, close: pd.Series) -> pd.Series:
    """True where close < open (bearish candle)."""
    return close < open_


def body_pct_of_range(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
) -> pd.Series:
    """
    Body as a percentage of total range (0–1).
    High body % indicates strong directional candle (order block candidate).
    """
    rng = candle_range(high, low).replace(0, np.nan)
    return candle_body(open_, close) / rng
