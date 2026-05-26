#!/usr/bin/env python3
"""Multi-factor scoring engine for Japanese stocks.

Computes 4 factor exposures (value, momentum, quality, volatility) from
yfinance fundamental data + price history, producing an equal-weighted
composite Z-score. Degrades gracefully to None when <2 factors available.

Usage:
    python factor_engine.py --ticker 7974.T
    python factor_engine.py --ticker 7974.T --output /tmp/factors.json
"""

import argparse
import json
import logging
import math
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_utils import yf_retry, load_ohlcv

logger = logging.getLogger(__name__)

MIN_FACTORS_REQUIRED = 2
FACTOR_NAMES = ["value", "momentum", "quality", "volatility"]

# Reference universe medians for Z-score normalization (TOPIX approximate)
# Used when peer comparison is not available
REFERENCE_MEDIANS = {
    "pe": 14.0, "pb": 1.2, "roe": 0.08, "de": 60.0,
    "beta": 0.85, "mom_3m": 0.0, "mom_6m": 0.0, "mom_12m": 0.0,
}


def _safe_info(info: dict, key: str):
    val = info.get(key)
    return float(val) if val is not None else None


def _z_score(value: float, median: float, mad: float = None) -> float:
    """Z-score normalized against reference median. Clamped to [-3, 3]."""
    if value is None or median is None or median == 0:
        return 0.0
    if mad is None:
        mad = abs(median) * 0.5  # default dispersion estimate
    if mad == 0:
        return 0.0
    return max(-3.0, min(3.0, (value - median) / mad))


def compute_factors(ticker: str) -> dict:
    """Compute 4-factor exposures for a single ticker.

    Returns dict with factor_scores, composite_z, data_coverage, warnings.
    Returns {"error": ..., "data_coverage": 0} on failure.
    """
    warnings = []
    factor_data = {}

    # 1. Fundamental data from yfinance
    try:
        info = yf_retry(lambda: yf.Ticker(ticker).info)
    except Exception as e:
        return {"error": f"yfinance info fetch failed: {e}", "data_coverage": 0,
                "composite_z": None, "factor_scores": {}}

    pe = _safe_info(info, "trailingPE")
    pb = _safe_info(info, "priceToBook")
    roe = _safe_info(info, "returnOnEquity")
    de = _safe_info(info, "debtToEquity")
    beta = _safe_info(info, "beta")

    # 2. Price data for momentum
    try:
        ohlcv = load_ohlcv(ticker, datetime.now().strftime("%Y-%m-%d"))
        if ohlcv.empty or len(ohlcv) < 2:
            closes = None
        else:
            closes = ohlcv["Close"]
    except Exception:
        closes = None

    mom_3m = mom_6m = mom_12m = None
    if closes is not None and len(closes) > 0:
        last = closes.iloc[-1]
        if len(closes) >= 63:
            mom_3m = (last / closes.iloc[-63] - 1) * 100
        if len(closes) >= 126:
            mom_6m = (last / closes.iloc[-126] - 1) * 100
        if len(closes) >= 252:
            mom_12m = (last / closes.iloc[-252] - 1) * 100

    # 3. Compute per-factor Z-scores
    scores = {}
    available_count = 0

    # Value factor: lower P/E, lower P/B = better value (invert Z)
    value_components = []
    if pe is not None:
        value_components.append(-_z_score(pe, REFERENCE_MEDIANS["pe"]))
    else:
        warnings.append(f"{ticker}: P/E data missing for value factor")
    if pb is not None:
        value_components.append(-_z_score(pb, REFERENCE_MEDIANS["pb"]))
    else:
        warnings.append(f"{ticker}: P/B data missing for value factor")
    if value_components:
        scores["value"] = round(sum(value_components) / len(value_components), 4)
        available_count += 1
    else:
        scores["value"] = None

    # Momentum factor: positive momentum = positive score
    mom_components = []
    if mom_3m is not None:
        mom_components.append(_z_score(mom_3m, REFERENCE_MEDIANS["mom_3m"]))
    if mom_6m is not None:
        mom_components.append(_z_score(mom_6m, REFERENCE_MEDIANS["mom_6m"]))
    if mom_12m is not None:
        mom_components.append(_z_score(mom_12m, REFERENCE_MEDIANS["mom_12m"]))
    if mom_components:
        scores["momentum"] = round(sum(mom_components) / len(mom_components), 4)
        available_count += 1
    else:
        scores["momentum"] = None
        warnings.append(f"{ticker}: No momentum data available")

    # Quality factor: higher ROE, lower D/E = better quality
    quality_components = []
    if roe is not None:
        quality_components.append(_z_score(roe, REFERENCE_MEDIANS["roe"]))
    else:
        warnings.append(f"{ticker}: ROE data missing for quality factor")
    if de is not None:
        quality_components.append(-_z_score(de, REFERENCE_MEDIANS["de"]))
    else:
        warnings.append(f"{ticker}: D/E data missing for quality factor")
    if quality_components:
        scores["quality"] = round(sum(quality_components) / len(quality_components), 4)
        available_count += 1
    else:
        scores["quality"] = None

    # Volatility factor: low beta = positive score (invert Z)
    if beta is not None:
        scores["volatility"] = round(-_z_score(beta, REFERENCE_MEDIANS["beta"]), 4)
        available_count += 1
    else:
        scores["volatility"] = None
        warnings.append(f"{ticker}: Beta data missing for volatility factor")

    # 4. Composite Z-score (equal weight)
    valid_scores = [v for v in scores.values() if v is not None]
    if len(valid_scores) >= MIN_FACTORS_REQUIRED:
        composite_z = round(sum(valid_scores) / len(valid_scores), 4)
    else:
        composite_z = None

    data_coverage = f"{available_count}/{len(FACTOR_NAMES)}"

    return {
        "ticker": ticker,
        "composite_z": composite_z,
        "data_coverage": data_coverage,
        "factor_scores": scores,
        "warnings": warnings,
        "raw_data": {
            "pe": pe, "pb": pb, "roe": roe, "de": de, "beta": beta,
            "mom_3m": round(mom_3m, 2) if mom_3m else None,
            "mom_6m": round(mom_6m, 2) if mom_6m else None,
            "mom_12m": round(mom_12m, 2) if mom_12m else None,
        },
    }


def classify_factor_signal(composite_z: float) -> str:
    """Classify factor composite Z-score into signal strength."""
    if composite_z is None:
        return None
    if composite_z > 1.0:
        return "STRONG_BUY"
    elif composite_z > 0.3:
        return "BUY"
    elif composite_z >= -0.3:
        return "NEUTRAL"
    elif composite_z >= -1.0:
        return "SELL"
    else:
        return "STRONG_SELL"


def main():
    parser = argparse.ArgumentParser(description="Multi-factor scoring engine")
    parser.add_argument("--ticker", required=True, help="Ticker to analyze")
    parser.add_argument("--output", "-o", help="Output JSON file path")
    args = parser.parse_args()

    result = compute_factors(args.ticker)
    output_json = json.dumps(result, ensure_ascii=False, indent=2, default=str)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Output written to {args.output}")

    signal = classify_factor_signal(result.get("composite_z"))
    print(f"\n=== Factor Analysis: {args.ticker} ===")
    print(f"Composite Z: {result.get('composite_z')}")
    print(f"Data coverage: {result.get('data_coverage')}")
    print(f"Signal: {signal}")
    for name, score in result.get("factor_scores", {}).items():
        print(f"  {name}: {score}")
    if result.get("warnings"):
        for w in result["warnings"]:
            print(f"  [WARN] {w}")

    print(output_json)


if __name__ == "__main__":
    main()
