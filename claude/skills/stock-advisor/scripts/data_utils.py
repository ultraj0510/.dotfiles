"""
Data utility functions extracted from TradingAgents dataflows layer.

Source: /home/ultraj/projects/TradingAgents/tradingagents/dataflows/
This module is a standalone extraction — no LangChain/LangGraph dependency.

yfinance auto_adjust=True returns prices adjusted for dividends and stock splits.
Backtest PnL calculations use price returns only; dividend income is excluded.
"""

import logging
import os
import shutil
import tempfile
import time

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.expanduser("~/.claude/skills/stock-advisor/scripts/cache/")

# === Extracted from y_finance.py:10 ===
_CUSTOM_INDICATORS = {"5d_return", "20d_return", "52w_position", "volume_ratio", "10d_return"}


# === Extracted from stockstats_utils.py:15-31 ===
def yf_retry(func, max_retries=3, base_delay=2.0):
    """Execute a yfinance call with exponential backoff on rate limits.

    yfinance raises YFRateLimitError on HTTP 429 responses but does not
    retry them internally. This wrapper adds retry logic specifically
    for rate limits. Other exceptions propagate immediately.
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except YFRateLimitError:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "Yahoo Finance rate limited, retrying in %.0fs (attempt %d/%d)",
                    delay, attempt + 1, max_retries,
                )
                time.sleep(delay)
            else:
                raise


# === Extracted from stockstats_utils.py:34-44 ===
def _clean_dataframe(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize a stock DataFrame for stockstats: parse dates, drop invalid rows, fill price gaps."""
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["Date"])

    price_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    data[price_cols] = data[price_cols].apply(pd.to_numeric, errors="coerce")
    data = data.dropna(subset=["Close"])
    data[price_cols] = data[price_cols].ffill().bfill()

    return data


# === Adapted from stockstats_utils.py:47-88 ===
# Changes:
#   - config.get_config() replaced with module constant CACHE_DIR
#   - CSV cache write uses tempfile + shutil.move for atomicity
def load_ohlcv(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch OHLCV data with caching, filtered to prevent look-ahead bias.

    Downloads 5 years of data up to today and caches per symbol. On
    subsequent calls the cache is reused. Rows after curr_date are
    filtered out so backtests never see future prices.
    """
    curr_date_dt = pd.to_datetime(curr_date)

    today_date = pd.Timestamp.today()
    start_date = today_date - pd.DateOffset(years=5)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = today_date.strftime("%Y-%m-%d")

    os.makedirs(CACHE_DIR, exist_ok=True)
    data_file = os.path.join(
        CACHE_DIR,
        f"{symbol}-YFin-data-{start_str}-{end_str}.csv",
    )

    if os.path.exists(data_file):
        data = pd.read_csv(data_file, on_bad_lines="skip")
    else:
        data = yf_retry(lambda: yf.download(
            symbol,
            start=start_str,
            end=end_str,
            multi_level_index=False,
            progress=False,
            auto_adjust=True,
        ))
        data = data.reset_index()
        # Atomic write: write to temp file then rename to prevent
        # corrupt cache from partial writes or concurrent access.
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, dir=CACHE_DIR,
        )
        try:
            data.to_csv(tmp.name, index=False)
            shutil.move(tmp.name, data_file)
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)

    data = _clean_dataframe(data)

    # Filter to curr_date to prevent look-ahead bias in backtesting
    data = data[data["Date"] <= curr_date_dt]

    return data


# === Extracted from y_finance.py:212-231 ===
def _compute_custom_indicator(data: pd.DataFrame, indicator: str) -> pd.Series:
    """Compute custom indicators not supported by stockstats."""
    close = data["Close"]
    volume = data["Volume"]

    if indicator == "5d_return":
        return close.pct_change(5) * 100
    elif indicator == "20d_return":
        return close.pct_change(20) * 100
    elif indicator == "52w_position":
        high_52w = close.rolling(252, min_periods=1).max()
        low_52w = close.rolling(252, min_periods=1).min()
        rng = high_52w - low_52w
        return ((close - low_52w) / rng.replace(0, float("nan"))) * 100
    elif indicator == "volume_ratio":
        avg_vol = volume.rolling(20, min_periods=1).mean()
        return volume / avg_vol.replace(0, float("nan"))
    elif indicator == "10d_return":
        return close.pct_change(10) * 100
    else:
        raise ValueError(f"Unknown custom indicator: {indicator}")


# === Extracted from y_finance.py:234-274 ===
def _get_stock_stats_bulk(
    symbol: str,
    indicator: str,
    curr_date: str,
) -> dict:
    """Optimized bulk calculation of stock stats indicators.

    Fetches data once and calculates indicator for all available dates.
    Returns dict mapping date strings to indicator values.
    """
    data = load_ohlcv(symbol, curr_date)

    if indicator in _CUSTOM_INDICATORS:
        date_col = data["Date"].dt.strftime("%Y-%m-%d")
        values = _compute_custom_indicator(data, indicator)
        result_dict = {}
        for date_str, val in zip(date_col, values):
            result_dict[date_str] = "N/A" if pd.isna(val) else f"{val:.2f}"
        return result_dict

    from stockstats import wrap
    df = wrap(data)
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")

    df[indicator]  # trigger stockstats to calculate the indicator

    result_dict = {}
    for _, row in df.iterrows():
        date_str = row["Date"]
        indicator_value = row[indicator]

        if pd.isna(indicator_value):
            result_dict[date_str] = "N/A"
        else:
            result_dict[date_str] = str(indicator_value)

    return result_dict
