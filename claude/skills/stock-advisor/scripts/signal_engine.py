#!/usr/bin/env python3
"""Rule-based signal detection engine for Japanese stocks.

Replaces the multi-agent LLM pipeline (18 calls) with numerical indicator
computation and deterministic signal rules. Output is structured JSON for
a single final LLM call (Step 3 of stock-advisor workflow).

Usage:
    python signal_engine.py --ticker 1515.T
    python signal_engine.py --tickers 1515.T,7974.T --output /tmp/signals.json
    python signal_engine.py --all  # reads default_tickers.txt
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf
import jpholiday

from data_utils import (
    _CUSTOM_INDICATORS,
    _get_stock_stats_bulk,
    load_ohlcv,
    yf_retry,
)

logger = logging.getLogger(__name__)

WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]

# All 17 indicators: 13 stockstats + 4 custom
STOCKSTATS_INDICATORS = [
    "close_50_sma", "close_200_sma", "close_10_ema",
    "macd", "macds", "macdh",
    "rsi",
    "boll", "boll_ub", "boll_lb",
    "atr",
    "vwma",
    "mfi",
]
ALL_INDICATORS = STOCKSTATS_INDICATORS + sorted(_CUSTOM_INDICATORS)

# Macro tickers
MACRO_TICKERS = {
    "vix": "^VIX",
    "sp500": "^GSPC",
    "usdjpy": "JPY=X",
    "us10y": "^TNX",
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TICKERS_FILE = os.path.join(SCRIPT_DIR, "default_tickers.txt")


def is_trading_day(date_str: str) -> bool:
    """Check if date_str is a Japanese stock market trading day."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    weekday = d.weekday()
    if weekday >= 5:  # Saturday or Sunday
        return False
    if jpholiday.is_holiday(d):
        return False
    return True


def get_latest_trading_day() -> str:
    """Return the most recent Japanese trading day as YYYY-MM-DD."""
    today = datetime.today()
    # Check up to 5 days back to handle long weekends
    for i in range(10):
        d = today - timedelta(days=i)
        ds = d.strftime("%Y-%m-%d")
        if d.weekday() < 5 and not jpholiday.is_holiday(d):
            return ds
    return today.strftime("%Y-%m-%d")


def fetch_macro_context() -> dict:
    """Fetch macro indicators: VIX, S&P500, USD/JPY, US 10Y yield."""
    result = {}
    today = pd.Timestamp.today()
    start = today - pd.DateOffset(days=10)

    for name, ticker in MACRO_TICKERS.items():
        try:
            data = yf_retry(lambda: yf.download(
                ticker, start=start.strftime("%Y-%m-%d"),
                end=today.strftime("%Y-%m-%d"),
                progress=False, auto_adjust=True,
            ))
            if data.empty:
                result[name] = {"value": None, "error": "no data"}
                continue

            close_series = data["Close"].squeeze()
            # Handle multi-level columns from yfinance
            if isinstance(close_series, pd.DataFrame):
                close_series = close_series.iloc[:, 0]
            close_values = close_series.dropna()
            if len(close_values) == 0:
                result[name] = {"value": None, "error": "all NaN"}
                continue

            latest_close = float(close_values.iloc[-1])
            prev_close = float(close_values.iloc[-2]) if len(close_values) >= 2 else None
            change_pct = ((latest_close - prev_close) / prev_close * 100) if prev_close else None
            result[name] = {
                "ticker": ticker,
                "value": round(latest_close, 2),
                "change_pct": round(change_pct, 2) if change_pct is not None else None,
            }
        except Exception as e:
            result[name] = {"value": None, "error": str(e)}

    return result


def fetch_analyst_target(ticker: str) -> dict:
    """Fetch analyst target price and recommendation from yfinance."""
    try:
        info = yf_retry(lambda: yf.Ticker(ticker).info)
    except Exception as e:
        return {"error": str(e)}

    target_mean = info.get("targetMeanPrice")
    target_high = info.get("targetHighPrice")
    target_low = info.get("targetLowPrice")
    num_analysts = info.get("numberOfAnalystOpinions")
    recommendation = info.get("recommendationKey")
    current = info.get("currentPrice") or info.get("regularMarketPreviousClose")

    result = {
        "target_mean": target_mean,
        "target_high": target_high,
        "target_low": target_low,
        "num_analysts": num_analysts,
        "recommendation": recommendation,
        "current_price": current,
    }

    if current and target_mean:
        divergence_pct = round((current - target_mean) / target_mean * 100, 2)
        result["divergence_pct"] = divergence_pct
        # Interpret divergence
        if divergence_pct <= -25:
            result["divergence_signal"] = "undervalued"
        elif divergence_pct >= 15:
            result["divergence_signal"] = "overvalued"
        else:
            result["divergence_signal"] = "fair"

    return result


def classify_signals(indicators: dict, macro: dict, analyst: dict) -> list:
    """Apply rule-based signal detection to indicator values."""
    signals = []

    rsi = _safe_float(indicators.get("rsi"))
    boll_lb = _safe_float(indicators.get("boll_lb"))
    close = _safe_float(indicators.get("close"))
    position_52w = _safe_float(indicators.get("52w_position"))
    ret_5d = _safe_float(indicators.get("5d_return"))
    vol_ratio = _safe_float(indicators.get("volume_ratio"))
    ret_20d = _safe_float(indicators.get("20d_return"))
    sma_50 = _safe_float(indicators.get("close_50_sma"))
    sma_200 = _safe_float(indicators.get("close_200_sma"))
    ret_10d = _safe_float(indicators.get("10d_return"))

    # Compute trend state for filter and adaptive logic
    trend_state = compute_trend_state(indicators)

    # Signal evaluation order (documented):
    # oversold_reversal → momentum_buy → overbought → momentum_breakdown
    # → drawdown_stop → trend_following → ma_support_bounce → death_cross
    # SELL signals evaluated later, overwriting BUY within the same day.

    # === BUY signals ===

    # Oversold reversal: RSI < 30 + near BB lower + 52w low zone
    # Trend filter: suppress in strong_downtrend, downgrade in downtrend
    if (rsi is not None and rsi < 30
            and position_52w is not None and position_52w < 25
            and trend_state != "strong_downtrend"):
        near_bb = False
        if close is not None and boll_lb is not None and close <= boll_lb * 1.02:
            near_bb = True
        vol_high = vol_ratio is not None and vol_ratio > 1.2
        vol_ok = vol_ratio is not None and vol_ratio > 1.0
        if near_bb and vol_high:
            strength = "strong"
        elif near_bb or vol_ok:
            strength = "moderate"
        else:
            strength = "weak"
        if trend_state == "downtrend" and strength == "moderate":
            strength = "weak"
        signals.append({
            "type": "BUY",
            "rule": "oversold_reversal",
            "strength": strength,
            "description": f"RSI={rsi:.1f}, 52w_position={position_52w:.1f}%"
                           + (f", near BB lower={boll_lb:.0f}" if near_bb else ""),
        })

    # Momentum BUY: 5d surge > 7% with volume confirmation
    if ret_5d is not None and ret_5d > 7:
        vol_high = vol_ratio is not None and vol_ratio > 1.5
        vol_ok = vol_ratio is not None and vol_ratio > 1.0
        if vol_high:
            strength = "strong"
        elif vol_ok:
            strength = "moderate"
        else:
            strength = "weak"
        signals.append({
            "type": "BUY",
            "rule": "momentum",
            "strength": strength,
            "description": f"5d_return={ret_5d:.1f}%, volume_ratio={vol_ratio:.1f}" if vol_ratio is not None else f"5d_return={ret_5d:.1f}%",
        })

    # === SELL signals ===

    # Overbought: RSI > 70 + near 52w high
    if rsi is not None and rsi > 70 and position_52w is not None and position_52w > 85:
        vol_high = vol_ratio is not None and vol_ratio > 1.2
        if rsi > 80 and vol_high:
            strength = "strong"
        elif rsi > 80 or vol_high:
            strength = "moderate"
        else:
            strength = "weak"
        signals.append({
            "type": "SELL",
            "rule": "overbought",
            "strength": strength,
            "description": f"RSI={rsi:.1f}, 52w_position={position_52w:.1f}%",
        })

    # Momentum breakdown: 5d sharp drop with high volume
    if ret_5d is not None and ret_5d < -7 and vol_ratio is not None and vol_ratio > 1.0:
        if vol_ratio > 2.0:
            strength = "strong"
        elif vol_ratio > 1.5:
            strength = "moderate"
        else:
            strength = "weak"
        signals.append({
            "type": "SELL",
            "rule": "momentum_breakdown",
            "strength": strength,
            "description": f"5d_return={ret_5d:.1f}%, volume_ratio={vol_ratio:.1f}",
        })

    # Drawdown stop: 20d decline triggers stop-loss
    if ret_20d is not None and ret_20d < -15:
        strength = "strong" if ret_20d < -20 else "moderate"
        signals.append({
            "type": "SELL",
            "rule": "drawdown_stop",
            "strength": strength,
            "description": f"20d_return={ret_20d:.1f}%, trend breakdown",
        })

    # Trend following BUY: golden cross active + positive mid-term momentum
    if (sma_50 is not None and sma_200 is not None and sma_50 > sma_200
            and close is not None and close > sma_50
            and ret_10d is not None and ret_10d > 3
            and vol_ratio is not None and vol_ratio > 0.8):
        signals.append({
            "type": "BUY", "rule": "trend_following",
            "strength": "strong" if vol_ratio > 1.2 else "moderate",
            "description": f"10d_return={ret_10d:.1f}%, golden cross active",
        })

    # MA support bounce BUY: price bounces off 50sma in uptrend
    if (sma_50 is not None and sma_200 is not None and sma_50 > sma_200
            and close is not None and sma_50 * 0.98 <= close <= sma_50 * 1.02
            and rsi is not None and rsi < 45):
        signals.append({
            "type": "BUY", "rule": "ma_support_bounce",
            "strength": "moderate" if rsi < 35 else "weak",
            "description": f"close near 50sma={sma_50:.0f}, RSI={rsi:.1f}",
        })

    # Death cross SELL: SMA ratio proximity detection
    # Uses sma_50/sma_200 ratio near 1.0 with sma_50 < sma_200 as approximate
    # cross detection. May fire repeatedly while SMAs remain close.
    if (sma_50 is not None and sma_200 is not None and sma_200 > 0
            and close is not None and close < sma_50
            and sma_50 < sma_200):
        sma_ratio = sma_50 / sma_200
        if 0.99 <= sma_ratio <= 1.01:
            signals.append({
                "type": "SELL", "rule": "death_cross",
                "strength": "strong",
                "description": f"50sma/200sma ratio={sma_ratio:.3f}, death cross detected",
            })

    # === Analyst-based signals ===
    div = analyst.get("divergence_pct")
    if div is not None:
        if div <= -25:
            signals.append({
                "type": "BUY",
                "rule": "analyst_undervalued",
                "strength": "moderate",
                "description": f"analyst divergence={div:.1f}%",
            })
        elif div >= 15:
            signals.append({
                "type": "SELL",
                "rule": "analyst_overvalued",
                "strength": "moderate",
                "description": f"analyst divergence={div:.1f}%",
            })

    # Sort by strength: strong > moderate
    signals.sort(key=lambda s: 0 if s["strength"] == "strong" else 1)

    return signals


def compute_overall_score(indicators: dict, signals: list) -> dict:
    """Compute an overall sentiment score from -100 (strong sell) to +100 (strong buy)."""
    score = 0

    rsi = _safe_float(indicators.get("rsi"))
    pos_52w = _safe_float(indicators.get("52w_position"))
    ret_5d = _safe_float(indicators.get("5d_return"))
    ret_20d = _safe_float(indicators.get("20d_return"))

    # RSI contribution
    if rsi is not None:
        if rsi < 30:
            score += 20
        elif rsi < 40:
            score += 10
        elif rsi > 70:
            score -= 20
        elif rsi > 60:
            score -= 10

    # 52w position
    if pos_52w is not None:
        if pos_52w < 25:
            score += 15
        elif pos_52w > 85:
            score -= 15

    # Recent momentum
    if ret_5d is not None:
        if ret_5d > 5:
            score += 10
        elif ret_5d < -5:
            score -= 10

    if ret_20d is not None:
        if ret_20d > 10:
            score += 10
        elif ret_20d < -10:
            score -= 10

    # Add signal contributions
    for sig in signals:
        weight = 15 if sig["strength"] == "strong" else (8 if sig["strength"] == "moderate" else 4)
        if sig["type"] == "BUY":
            score += weight
        elif sig["type"] == "SELL":
            score -= weight

    score = max(-100, min(100, score))

    if score >= 40:
        recommendation = "BUY"
    elif score >= 15:
        recommendation = "HOLD_BUY"
    elif score > -15:
        recommendation = "HOLD"
    elif score > -40:
        recommendation = "HOLD_SELL"
    else:
        recommendation = "SELL"

    return {"score": score, "recommendation": recommendation}


def compute_trend_state(indicators: dict) -> str:
    close = _safe_float(indicators.get("close"))
    sma_50 = _safe_float(indicators.get("close_50_sma"))
    sma_200 = _safe_float(indicators.get("close_200_sma"))
    ret_20d = _safe_float(indicators.get("20d_return"))

    if close is None or sma_50 is None or sma_200 is None:
        return "unknown"

    above_50sma = close > sma_50
    above_200sma = close > sma_200
    golden_cross = sma_50 > sma_200

    if above_50sma and above_200sma and golden_cross:
        if ret_20d is not None and ret_20d > 5:
            return "strong_uptrend"
        return "weak_uptrend"
    elif above_50sma and not golden_cross:
        return "weak_uptrend"
    elif not above_50sma and not above_200sma and not golden_cross:
        if ret_20d is not None and ret_20d < -5:
            return "strong_downtrend"
        return "downtrend"
    elif not above_50sma and above_200sma:
        return "downtrend"
    else:
        return "ranging"


def compute_suggested_entry(indicators: dict, analyst: dict) -> float:
    """Compute suggested entry price from BB lower and analyst target.

    Formula: max(BB_lower, analyst_target_mean * 0.75)
    Returns None when neither value is available.
    """
    bb_lower = _safe_float(indicators.get("boll_lb"))
    target_mean = analyst.get("target_mean")
    if target_mean is not None:
        target_mean = _safe_float(target_mean)

    candidates = []
    if bb_lower is not None:
        candidates.append(bb_lower)
    if target_mean is not None:
        candidates.append(target_mean * 0.75)

    if not candidates:
        return None
    return round(max(candidates), 2)


def analyze_ticker(ticker: str, date_str: str) -> dict:
    """Run full analysis for a single ticker."""
    try:
        indicators = {}
        for ind in ALL_INDICATORS:
            bulk = _get_stock_stats_bulk(ticker, ind, date_str)
            indicators[ind] = bulk.get(date_str, "N/A")

        # Also get latest close for BB proximity check
        ohlcv = load_ohlcv(ticker, date_str)
        if not ohlcv.empty:
            latest = ohlcv.iloc[-1]
            indicators["close"] = str(latest.get("Close", "N/A"))
            indicators["date"] = str(latest.get("Date", date_str))

        macro = fetch_macro_context()
        analyst = fetch_analyst_target(ticker)
        signals = classify_signals(indicators, macro, analyst)
        score = compute_overall_score(indicators, signals)
        trend_state = compute_trend_state(indicators)

        return {
            "ticker": ticker,
            "date": date_str,
            "weekday_ja": WEEKDAY_JP[datetime.strptime(date_str, "%Y-%m-%d").weekday()],
            "is_trading_day": is_trading_day(date_str),
            "trend_state": trend_state,
            "indicators": indicators,
            "signals": signals,
            "score": score,
            "macro": macro,
            "analyst": analyst,
            "suggested_entry": compute_suggested_entry(indicators, analyst),
        }
    except Exception as e:
        logger.exception("Failed to analyze %s", ticker)
        return {
            "ticker": ticker,
            "date": date_str,
            "error": str(e),
        }


def _safe_float(val):
    """Convert indicator value to float, returning None on failure."""
    if val is None or val == "N/A":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def load_default_tickers() -> list:
    """Load ticker list from default_tickers.txt. One ticker per line."""
    tickers = []
    if os.path.exists(DEFAULT_TICKERS_FILE):
        with open(DEFAULT_TICKERS_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    tickers.append(line)
    return tickers


def main():
    parser = argparse.ArgumentParser(description="Stock signal detection engine")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ticker", help="Single ticker to analyze")
    group.add_argument("--tickers", help="Comma-separated ticker list")
    group.add_argument("--all", action="store_true", help="Analyze all tickers in default_tickers.txt")
    parser.add_argument("--output", "-o", help="Output JSON file path (default: stdout)")
    parser.add_argument("--date", help="Reference date YYYY-MM-DD (default: latest trading day)")
    parser.add_argument("--factor-mode", action="store_true",
                        help="Compute factor scores alongside binary signals")
    args = parser.parse_args()

    date_str = args.date or get_latest_trading_day()

    if args.ticker:
        tickers = [args.ticker]
    elif args.tickers:
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = load_default_tickers()
        if not tickers:
            print("ERROR: --all specified but default_tickers.txt is empty or missing", file=sys.stderr)
            sys.exit(1)

    results = {
        "generated_at": datetime.now().isoformat(),
        "reference_date": date_str,
        "ticker_count": len(tickers),
        "factor_mode": args.factor_mode,
        "results": [],
    }

    for ticker in tickers:
        result = analyze_ticker(ticker.strip(), date_str)
        if args.factor_mode:
            try:
                from factor_engine import compute_factors, classify_factor_signal
                factor_result = compute_factors(ticker.strip())
                factor_result["factor_signal"] = classify_factor_signal(
                    factor_result.get("composite_z"))
                result["factor_scores"] = factor_result
            except Exception as e:
                result["factor_scores"] = {"error": str(e), "data_coverage": "0/4"}
        results["results"].append(result)

    output_json = json.dumps(results, ensure_ascii=False, indent=2, default=str)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Output written to {args.output}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
