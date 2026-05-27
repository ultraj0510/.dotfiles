"""Backtest result cache with content-hash invalidation.

Caches full backtest JSON results keyed by ticker + strategy + end_date.
Auto-invalidates when signal_rules.py thresholds or backtest_engine.py
DEFAULT_THRESHOLDS change (content-hash mismatch).

Cache location: scripts/cache/backtest/
"""

import hashlib
import json
import os
import shutil
import tempfile
import time

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache", "backtest")


def _scripts_dir():
    return os.path.dirname(__file__)


def compute_config_hash():
    """Hash of signal_rules.py + backtest_engine.py DEFAULT_THRESHOLDS.

    When the hash changes, all cached backtest results are invalidated because
    the signal logic or thresholds have changed.
    """
    hasher = hashlib.sha256()

    # Hash signal_rules.py source
    rules_path = os.path.join(_scripts_dir(), "signal_rules.py")
    if os.path.exists(rules_path):
        with open(rules_path, "rb") as f:
            hasher.update(f.read())

    # Hash DEFAULT_THRESHOLDS from backtest_engine.py
    from signal_rules import (
        RSI_LOWER, RSI_UPPER,
        POSITION_52W_LOWER, POSITION_52W_UPPER,
        MOMENTUM_5D, BREAKDOWN_5D, BREAKDOWN_VOL, DRAWDOWN_20D,
    )
    thresholds_repr = repr(sorted({
        "rsi_lower": RSI_LOWER,
        "rsi_upper": RSI_UPPER,
        "position_52w_lower": POSITION_52W_LOWER,
        "position_52w_upper": POSITION_52W_UPPER,
        "momentum_5d": MOMENTUM_5D,
        "breakdown_5d": BREAKDOWN_5D,
        "breakdown_vol": BREAKDOWN_VOL,
        "drawdown_20d": DRAWDOWN_20D,
    }.items()))
    hasher.update(thresholds_repr.encode())

    return hasher.hexdigest()[:16]


def get_cache_path(ticker, strategy, end_date):
    """Return cache file path for the given parameters."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    filename = f"{ticker}-{strategy}-{end_date}.json"
    return os.path.join(CACHE_DIR, filename)


def load_cached_result(ticker, strategy, end_date, max_age=86400):
    """Load cached backtest result if valid, otherwise None.

    Args:
        ticker: Ticker symbol (e.g. '7974.T')
        strategy: Strategy mode ('default', 'trend', 'contrarian')
        end_date: Backtest end date (YYYY-MM-DD)
        max_age: Maximum cache age in seconds (default 86400 = 24h)

    Returns:
        dict on cache hit, None on miss or invalid cache
    """
    cache_path = get_cache_path(ticker, strategy, end_date)
    if not os.path.exists(cache_path):
        return None

    cache_age = time.time() - os.path.getmtime(cache_path)
    if cache_age >= max_age:
        return None

    try:
        with open(cache_path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

    # Content-hash invalidation: if signal rules have changed since cache
    # was written, treat as cache miss
    current_hash = compute_config_hash()
    cached_hash = data.get("_config_hash")
    if cached_hash != current_hash:
        return None

    return data


def save_cached_result(ticker, strategy, end_date, result):
    """Save backtest result to cache atomically.

    Writes to a temp file then shutil.move to prevent corrupt cache from
    partial writes or concurrent access.
    """
    # Inject config hash for invalidation on next read
    result["_config_hash"] = compute_config_hash()

    cache_path = get_cache_path(ticker, strategy, end_date)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir=CACHE_DIR,
    )
    try:
        json.dump(result, tmp, ensure_ascii=False, indent=2, default=str)
        tmp.flush()
        os.fsync(tmp.fileno())
        shutil.move(tmp.name, cache_path)
    finally:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)


def cleanup_old_cache(max_age_days=7):
    """Remove cache files older than max_age_days."""
    if not os.path.isdir(CACHE_DIR):
        return
    cutoff = time.time() - (max_age_days * 86400)
    for fname in os.listdir(CACHE_DIR):
        fpath = os.path.join(CACHE_DIR, fname)
        if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
            os.unlink(fpath)
