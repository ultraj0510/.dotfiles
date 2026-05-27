#!/usr/bin/env python3
"""Personalized trade advisory tool based on portfolio position analysis.

Analyzes current position, technical signals, historical signal win rates,
and risk factors to generate structured trade advice.

Usage:
    python trade_advisor.py --ticker 7203.T --cost-basis 2800 --shares 100 --mode spot
    python trade_advisor.py --ticker 7203.T --cost-basis 2800 --shares 100 --mode margin --output advice.json
"""

import argparse
import json
import logging
import math
import os
import signal
import sys
from datetime import datetime, timedelta

import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_utils import yf_retry, load_ohlcv
from signal_engine import analyze_ticker, get_latest_trading_day
from backtest_cache import load_cached_result
from backtest_engine import (
    generate_signals,
    simulate_trades,
    _compute_signal_census,
)

logger = logging.getLogger(__name__)

TREND_STRENGTH_MAP = {
    "strong_uptrend": 1.0,
    "weak_uptrend": 0.5,
    "ranging": 0.0,
    "downtrend": 0.5,
    "strong_downtrend": 1.0,
    "unknown": 0.0,
}

UP_TREND_STATES = {"strong_uptrend", "weak_uptrend"}
DOWN_TREND_STATES = {"strong_downtrend", "downtrend"}

OPINION_THRESHOLDS = [
    (60, "STRONG_BUY", "買い増し推奨"),
    (30, "BUY_MORE", "押し目買い検討"),
    (-10, "HOLD", "現状維持"),
    (-40, "REDUCE", "リバウンド時に一部売却"),
]

FALLBACK_OPINION = ("SELL", "全株売却")

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")


def _cache_path(ticker: str, target_years: int) -> str:
    return os.path.join(
        CACHE_DIR, f"{ticker}-signal-win-rates-{target_years}y.json"
    )


def _load_cache(ticker: str, target_years: int):
    """Load cached win-rate data if present and less than 1 hour old."""
    path = _cache_path(ticker, target_years)
    if not os.path.exists(path):
        return None
    try:
        age = datetime.now().timestamp() - os.path.getmtime(path)
        if age > 3600:
            return None
        with open(path) as f:
            data = json.load(f)
        return (
            data.get("per_rule"),
            data.get("active_rules"),
            data.get("max_holding_days", 0),
        )
    except Exception:
        return None


def _save_cache(ticker: str, target_years: int, per_rule: dict,
                 active_rules: list, max_holding_days: int):
    """Save win-rate data to cache."""
    path = _cache_path(ticker, target_years)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump({
            "per_rule": per_rule,
            "active_rules": active_rules,
            "max_holding_days": max_holding_days,
        }, f, ensure_ascii=False, indent=2, default=str)


def _safe_float(val):
    if val is None or val == "N/A":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


class BacktestTimeoutError(Exception):
    pass


def _timeout_handler(signum, frame):
    raise BacktestTimeoutError("Backtest timed out")


def _is_japan_market_open() -> bool:
    """Check if Tokyo Stock Exchange is currently open."""
    import jpholiday
    now = datetime.now()
    # Check weekday
    if now.weekday() >= 5:
        return False
    # Check Japanese holiday
    if jpholiday.is_holiday(now.date()):
        return False
    # TSE hours: 9:00-11:30, 12:30-15:00 JST (UTC+9)
    t = now.hour * 60 + now.minute
    return (540 <= t < 690) or (750 <= t < 900)  # 9:00-11:30, 12:30-15:00


def fetch_market_price(ticker: str) -> float:
    """Fetch current market price for the given ticker via yfinance.

    During TSE trading hours, uses real-time currentPrice.
    Outside trading hours, falls back to previous close.
    """
    info = yf_retry(lambda: yf.Ticker(ticker).info)
    if _is_japan_market_open():
        price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("regularMarketPreviousClose")
    else:
        price = info.get("regularMarketPreviousClose") or info.get("regularMarketPrice") or info.get("currentPrice")
    if price is None:
        raise ValueError(f"Could not fetch market price for {ticker}")
    return float(price)


def compute_pnl(market_price: float, cost_basis: float, shares: int):
    """Compute unrealized P&L values."""
    pnl = round((market_price - cost_basis) * shares, 2)
    pnl_pct = round((market_price - cost_basis) / cost_basis * 100, 2)
    return pnl, pnl_pct


def _extract_win_rates_from_result(bt_result: dict):
    """Extract per-rule win rates from a pre-computed backtest result dict.

    Returns (per_rule, active_rules, max_holding_days) matching the format
    expected by callers of run_backtest_win_rates().
    """
    census = bt_result.get("baseline", {}).get("signal_census", {})
    trades = bt_result.get("baseline", {}).get("trades", [])

    per_rule = {}
    active_rules = []
    max_holding_days = 0

    for rule_name, info in census.items():
        if rule_name == "totals":
            continue
        wr = info.get("win_rate")
        cnt = info.get("count", 0)
        per_rule[rule_name] = {
            "win_rate": round(wr, 1) if wr is not None else None,
            "trade_count": cnt,
        }
        if wr is not None and cnt > 0:
            entry = {
                "rule": rule_name,
                "historical_win_rate": round(wr, 1),
                "trade_count": cnt,
            }
            if cnt < 5:
                entry["caveat"] = "low_sample"
            active_rules.append(entry)

    for t in trades:
        hd = t.get("holding_days", 0)
        if hd > max_holding_days:
            max_holding_days = hd

    return per_rule, active_rules, max_holding_days


def run_backtest_win_rates(ticker: str, date_str: str, target_years: int,
                           backtest_result: dict = None):
    """Run a backtest and compute per-rule signal win rates.

    Results are cached for 1 hour. Returns (per_rule, active_win_rates_list,
    max_holding_days) or (None, [], 0) on failure/timeout.

    If backtest_result is provided, extracts win rates from it without
    re-running the backtest.
    """
    # If pre-computed backtest result provided, extract win rates directly
    if backtest_result is not None:
        return _extract_win_rates_from_result(backtest_result)

    end_dt = datetime.strptime(date_str, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=int(365.25 * target_years))
    start_date = start_dt.strftime("%Y-%m-%d")

    # Check cache first (existing 1h file cache)
    cached = _load_cache(ticker, target_years)
    if cached is not None:
        return cached

    # Also check the new backtest result cache (24h TTL)
    from backtest_cache import load_cached_result as _lcr
    bt_cached = _lcr(ticker, "default", start_date, date_str)
    if bt_cached is not None:
        return _extract_win_rates_from_result(bt_cached)


    original_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(30)
    try:
        sig_df = generate_signals(ticker, start_date, date_str)
        metrics = simulate_trades(sig_df, ticker=ticker)
        census = _compute_signal_census(sig_df, metrics.get("trades", []))
        signal.alarm(0)

        per_rule = {}
        active_rules = []
        max_holding_days = 0

        for rule_name, info in census.items():
            if rule_name == "totals":
                continue
            wr = info.get("win_rate")
            cnt = info.get("count", 0)
            per_rule[rule_name] = {
                "win_rate": round(wr, 1) if wr is not None else None,
                "trade_count": cnt,
            }
            if wr is not None and cnt > 0:
                entry = {
                    "rule": rule_name,
                    "historical_win_rate": round(wr, 1),
                    "trade_count": cnt,
                }
                if cnt < 5:
                    entry["caveat"] = "low_sample"
                active_rules.append(entry)

        for t in metrics.get("trades", []):
            hd = t.get("holding_days", 0)
            if hd > max_holding_days:
                max_holding_days = hd

        _save_cache(ticker, target_years, per_rule, active_rules, max_holding_days)
        return per_rule, active_rules, max_holding_days

    except (BacktestTimeoutError, Exception) as e:
        signal.alarm(0)
        logger.warning("Backtest failed or timed out: %s", e)
        return None, [], 0
    finally:
        signal.signal(signal.SIGALRM, original_handler)


def compute_pnl_contribution(unrealized_pnl_pct: float) -> float:
    """Compute P&L contribution in range [-30, 30]."""
    if unrealized_pnl_pct > 5:
        return min(int(unrealized_pnl_pct / 5) * 10, 30)
    elif unrealized_pnl_pct < -5:
        return max(int(unrealized_pnl_pct / 5) * 10, -30)
    return 0.0


def check_signal_conformation(ticker: str, date_str: str,
                               active_rules: list) -> dict:
    """Check if each active signal persisted on 2 of the last 3 trading days.

    Returns dict mapping rule_name -> {"conformed": bool, "recent_days": int}.
    Non-conformed signals get a "signal_not_confirmed" caveat.
    """
    if not active_rules:
        return {}

    # Fetch last 4 trading days of signals (need 3 days prior to date_str)
    lookback_start = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=10)).strftime("%Y-%m-%d")
    try:
        sig_df = generate_signals(ticker, lookback_start, date_str)
    except Exception:
        return {}

    if sig_df.empty or len(sig_df) < 3:
        return {}

    # Get last 3 days of signals (including date_str)
    recent = sig_df.tail(3)
    rule_days = {}
    for _, row in recent.iterrows():
        rule = row.get("signal_rule")
        if rule:
            rule_days[rule] = rule_days.get(rule, 0) + 1

    result = {}
    current_rules = {s["rule"] for s in active_rules if isinstance(s, dict) and "rule" in s}
    for rule in current_rules:
        days_fired = rule_days.get(rule, 0)
        conformed = days_fired >= 2
        result[rule] = {
            "conformed": conformed,
            "recent_days": days_fired,
        }

    return result



def compute_trend_alignment(unrealized_pnl_pct: float, trend_state: str) -> float:
    """Compute trend alignment contribution in range [-25, 25]."""
    strength = TREND_STRENGTH_MAP.get(trend_state, 0.0)
    if unrealized_pnl_pct > 0 and trend_state in UP_TREND_STATES:
        return 25.0 * strength
    elif unrealized_pnl_pct < 0 and trend_state in DOWN_TREND_STATES:
        return -25.0 * strength
    return 0.0


def map_score_to_opinion(total_score: float):
    """Map advisory score to opinion label and Japanese description."""
    for threshold, opinion, opinion_ja in OPINION_THRESHOLDS:
        if total_score >= threshold:
            return opinion, opinion_ja
    return FALLBACK_OPINION


def compute_confidence(total_score: float, trend_state: str) -> str:
    if abs(total_score) > 50:
        return "high"
    elif abs(total_score) > 20:
        return "moderate"
    return "low"


def compute_advisory(
    overall_score_result: dict,
    trend_state: str,
    unrealized_pnl_pct: float,
    signal_win_rates: dict,
) -> dict:
    """Compute advisory score breakdown and opinion."""
    # Factor 1: Overall score contribution (raw range [-50, 50])
    score_val = overall_score_result.get("score", 0)
    factor1 = score_val / 100.0 * 50

    # Factor 2: Historical win rate contribution (raw range [-50, 50])
    active_signals = signal_win_rates.get("active_signals", [])
    win_rates = [
        s["historical_win_rate"]
        for s in active_signals
        if s.get("historical_win_rate") is not None
    ]
    if win_rates:
        avg_win_rate = sum(win_rates) / len(win_rates)
    else:
        avg_win_rate = 50.0
    factor2 = avg_win_rate - 50

    # Factor 3: Trend alignment (raw range [-25, 25])
    factor3 = compute_trend_alignment(unrealized_pnl_pct, trend_state)

    # Factor 4: P&L contribution (raw range [-30, 30])
    factor4 = compute_pnl_contribution(unrealized_pnl_pct)

    total = factor1 + factor2 + factor3 + factor4
    opinion, opinion_ja = map_score_to_opinion(total)
    confidence = compute_confidence(total, trend_state)

    return {
        "opinion": opinion,
        "opinion_ja": opinion_ja,
        "confidence": confidence,
        "score_breakdown": {
            "overall_score_contribution": round(factor1, 1),
            "historical_win_rate_contribution": round(factor2, 1),
            "trend_alignment_contribution": round(factor3, 1),
            "pnl_contribution": round(factor4, 1),
            "total": round(total, 1),
        },
        "reasoning": _format_reasoning(
            opinion, opinion_ja, total, score_val, avg_win_rate,
            trend_state, unrealized_pnl_pct,
        ),
    }


def _format_reasoning(
    opinion, opinion_ja, total, overall_score,
    avg_win_rate, trend_state, pnl_pct,
):
    parts = [f"Total score: {total:.1f} -> {opinion} ({opinion_ja})"]
    parts.append(
        f"Signal engine score: {overall_score} | "
        f"Avg historical win rate: {avg_win_rate:.1f}%"
    )
    parts.append(f"Trend: {trend_state} | Unrealized P&L: {pnl_pct:+.2f}%")
    return " | ".join(parts)


def compute_target_prices(
    indicators: dict,
    analyst: dict,
    market_price: float,
    opinion: str,
):
    """Compute target prices and stop loss."""
    boll_ub = _safe_float(indicators.get("boll_ub"))
    boll_lb = _safe_float(indicators.get("boll_lb"))
    atr = _safe_float(indicators.get("atr"))

    target1 = None
    stop_loss = None

    bullish_opinions = {"STRONG_BUY", "BUY_MORE"}
    bearish_opinions = {"REDUCE", "SELL"}

    if opinion in bullish_opinions:
        if boll_ub is not None:
            target1 = round(boll_ub, 2)
        if atr is not None:
            stop_loss = round(market_price - 2 * atr, 2)
    elif opinion in bearish_opinions:
        if boll_lb is not None:
            target1 = round(boll_lb, 2)
        if atr is not None:
            stop_loss = round(market_price + 2 * atr, 2)
    else:
        # HOLD: nearest BB band
        if boll_ub is not None and boll_lb is not None:
            dist_up = abs(market_price - boll_ub)
            dist_low = abs(market_price - boll_lb)
            target1 = round(boll_ub if dist_up < dist_low else boll_lb, 2)
        if atr is not None:
            stop_loss = round(market_price - 2 * atr, 2)

    # Stretch target: analyst mean target
    target2 = analyst.get("target_mean")

    # Risk-reward ratio
    risk_reward = None
    if target1 is not None and stop_loss is not None and stop_loss != market_price:
        if opinion in bullish_opinions | {"HOLD"}:
            if market_price > stop_loss:
                risk_reward = round(
                    (target1 - market_price) / (market_price - stop_loss), 1
                )
        else:
            if stop_loss > market_price:
                risk_reward = round(
                    (market_price - target1) / (stop_loss - market_price), 1
                )

    return {
        "target_price_1": target1,
        "target_price_2": target2,
        "stop_loss": stop_loss,
        "risk_reward_ratio": risk_reward,
    }


def assess_risk(
    market_price: float,
    shares: int,
    mode: str,
    portfolio_value: float,
    indicators: dict,
    signals: list,
    atr_value: float,
) -> dict:
    """Build risk assessment with factors and overall risk level."""
    factors = []
    position_value = market_price * shares

    # Position size risk
    if portfolio_value and portfolio_value > 0:
        ratio = position_value / portfolio_value
        if ratio > 0.25:
            severity = "high"
        elif ratio > 0.10:
            severity = "moderate"
        else:
            severity = "low"
        factors.append({
            "name": "position_size",
            "severity": severity,
            "detail": (
                f"Position value {position_value:,.0f} yen = "
                f"{ratio:.1%} of portfolio ({portfolio_value:,.0f} yen)"
            ),
        })

    # Concentration risk
    overbought_rules = {"overbought", "analyst_overvalued", "overbought_sell"}
    active_rules = {s.get("rule") for s in signals}
    if overbought_rules & active_rules:
        factors.append({
            "name": "concentration",
            "severity": "moderate",
            "detail": "Overbought signal active; consider reducing position size",
        })

    # Margin risk
    if mode == "margin":
        factors.append({
            "name": "margin",
            "severity": "moderate",
            "detail": "Margin position active; monitor cost rate and expiry",
        })

    # Volatility risk
    if atr_value is not None and atr_value > 0:
        atr_pct = (atr_value / market_price) * 100
        if atr_pct > 5:
            v_severity = "high"
        elif atr_pct > 2:
            v_severity = "moderate"
        else:
            v_severity = "low"
        factors.append({
            "name": "volatility",
            "severity": v_severity,
            "detail": f"ATR = {atr_value:.2f} ({atr_pct:.1f}% of price)",
        })

    # Overall risk = most severe factor
    severity_order = {"low": 0, "moderate": 1, "high": 2}
    overall_risk = "low"
    for f in factors:
        if severity_order.get(f["severity"], 0) > severity_order.get(overall_risk, 0):
            overall_risk = f["severity"]

    return {"factors": factors, "overall_risk": overall_risk}


def _fetch_historical_vol(ticker: str, lookback_days: int = 60) -> float:
    """Fetch realized annualized volatility over lookback_days."""
    ohlcv = load_ohlcv(ticker, datetime.now().strftime("%Y-%m-%d"))
    if ohlcv.empty or len(ohlcv) < 2:
        return None
    closes = ohlcv["Close"].tail(lookback_days + 1)
    if len(closes) < 2:
        return None
    returns = closes.pct_change().dropna()
    if len(returns) < 2:
        return None
    daily_vol = returns.std()
    return daily_vol * math.sqrt(252)


def compute_inverse_vol_weights(positions: list, portfolio_value: float) -> dict:
    """Compute inverse-volatility-weighted position sizes.

    positions: list of dicts with {ticker, market_price, shares, mode}
    Returns weights dict with per-ticker allocation details.
    """
    vols = {}
    for p in positions:
        ticker = p["ticker"]
        vol = _fetch_historical_vol(ticker, 60)
        vols[ticker] = vol if vol and vol > 0 else None

    # Compute raw inverse-vol weights (handle None vol as equal weight)
    inv_vols = {}
    for ticker, vol in vols.items():
        inv_vols[ticker] = 1.0 / vol if vol else 0.0

    total_inv = sum(inv_vols.values())
    if total_inv <= 0:
        # All vols are None/zero, fall back to equal weight
        n = len(positions)
        raw_weights = {p["ticker"]: 1.0 / n for p in positions}
    else:
        raw_weights = {t: inv / total_inv for t, inv in inv_vols.items()}
        # Zero-vol tickers get equal share of remaining
        zero_vol_tickers = [p["ticker"] for p in positions if vols.get(p["ticker"]) is None]
        if zero_vol_tickers:
            eq_weight = 1.0 / len(positions)
            for zt in zero_vol_tickers:
                raw_weights[zt] = eq_weight

    # Apply constraints: max 25%, round to 100-share units, min JPY 400K or 100 shares
    allocations = []
    for p in positions:
        ticker = p["ticker"]
        price = p["market_price"]
        raw_w = raw_weights.get(ticker, 0.0)

        # Cap at 25%
        capped_w = min(raw_w, 0.25)
        target_value = portfolio_value * capped_w
        target_shares = target_value / price

        # Round to 100-share units
        rounded_shares = max(round(target_shares / 100) * 100, 0)

        # Minimum position: max(100 shares, JPY 400K)
        min_shares = max(100, int(400000 / price) + (1 if 400000 % price > 0 else 0))
        min_shares = (min_shares // 100 + (1 if min_shares % 100 > 0 else 0)) * 100
        if capped_w > 0.02 and rounded_shares < min_shares:
            rounded_shares = min_shares
        if capped_w <= 0.02:
            rounded_shares = 0  # below 2% threshold, drop position

        actual_value = rounded_shares * price
        actual_w = actual_value / portfolio_value if portfolio_value > 0 else 0.0

        allocations.append({
            "ticker": ticker,
            "market_price": price,
            "current_shares": p.get("shares", 0),
            "raw_weight": round(raw_w, 4),
            "capped_weight": round(capped_w, 4),
            "target_shares": rounded_shares,
            "target_value": actual_value,
            "actual_weight": round(actual_w, 4),
            "deviation_pct": round((actual_w - capped_w) / capped_w * 100, 1) if capped_w > 0 else 0.0,
            "mode": p.get("mode", "spot"),
            "vol_used": round(vols.get(ticker), 4) if vols.get(ticker) else None,
        })

    # Check weight sum post-rounding
    total_actual_w = sum(a["actual_weight"] for a in allocations)
    rebalancing_needed = any(
        abs(a["actual_weight"] - a["capped_weight"]) > a["capped_weight"] * 0.5
        for a in allocations if a["capped_weight"] > 0
    )

    return {
        "portfolio_value": portfolio_value,
        "target_weights": {a["ticker"]: a["capped_weight"] for a in allocations},
        "allocations": allocations,
        "total_actual_weight": round(total_actual_w, 4),
        "rebalancing_needed": rebalancing_needed,
        "rebalancing_frequency": "every 20 trading days (~4 weeks)",
        "early_rebalance_trigger": "any weight deviates >50% from target at last rebalance",
    }


def _load_portfolio_yaml(path: str) -> dict:
    """Load portfolio.yaml and return structured position data."""
    import yaml
    with open(path) as f:
        data = yaml.safe_load(f)
    return data


def arbitrate_factor_vs_rule(factor_signal: str, binary_opinion: str) -> dict:
    """Resolve factor score vs binary rule conflict using the arbitration matrix.

    Returns {adjustment: float, action: str, reasoning: str}.
    adjustment is a multiplier on position weight (1.0 = no change).
    """
    if factor_signal is None:
        return {"adjustment": 1.0, "action": "BINARY_ONLY",
                "reasoning": "ファクターデータ不足、バイナリルールのみで判断"}

    # Map binary opinion to matrix categories
    binary_buy = {"STRONG_BUY", "BUY_MORE"}
    binary_sell = {"REDUCE", "SELL"}
    if binary_opinion in binary_buy:
        binary_cat = "BUY"
    elif binary_opinion in binary_sell:
        binary_cat = "SELL"
    else:
        binary_cat = "HOLD"

    # Arbitration matrix
    matrix = {
        ("STRONG_BUY", "BUY"):   (1.25, "OVERWEIGHT", "ファクター強気+バイナリ買い → オーバーウェイト(+25%)"),
        ("STRONG_BUY", "SELL"):  (1.0, "NEUTRAL", "ファクター強気でもバイナリ売り優先 → 中立"),
        ("STRONG_BUY", "HOLD"):  (1.10, "SLIGHT_OVERWEIGHT", "ファクター強気+保留 → ややオーバーウェイト(+10%)"),
        ("BUY", "BUY"):          (1.10, "SLIGHT_OVERWEIGHT", "ファクター買い+バイナリ買い → ややオーバーウェイト(+10%)"),
        ("BUY", "SELL"):         (1.0, "NEUTRAL", "ファクター買いでもバイナリ売り優先 → 中立"),
        ("BUY", "HOLD"):         (1.0, "WEIGHT", "ファクター買い+保留 → 目標ウェイト維持"),
        ("NEUTRAL", "BUY"):      (1.0, "WEIGHT", "ファクター中立 → バイナリルールに従う"),
        ("NEUTRAL", "SELL"):     (1.0, "WEIGHT", "ファクター中立 → バイナリルールに従う"),
        ("NEUTRAL", "HOLD"):     (1.0, "WEIGHT", "ファクター中立+保留 → 目標ウェイト維持"),
        ("SELL", "BUY"):         (1.0, "WEIGHT", "バイナリ買いがファクター売りを抑制 → 目標ウェイト維持"),
        ("SELL", "SELL"):        (0.75, "UNDERWEIGHT", "ファクター売り+バイナリ売り → アンダーウェイト(-25%)"),
        ("SELL", "HOLD"):        (0.90, "SLIGHT_UNDERWEIGHT", "ファクター売り+保留 → ややアンダーウェイト(-10%)"),
        ("STRONG_SELL", "BUY"):  (1.0, "WEIGHT", "バイナリ買いがファクター強売りを抑制 → 目標ウェイト維持"),
        ("STRONG_SELL", "SELL"): (0.0, "EXIT", "ファクター強売り+バイナリ売り → 全株売却"),
        ("STRONG_SELL", "HOLD"): (0.75, "UNDERWEIGHT", "ファクター強売り+保留 → アンダーウェイト(-25%)"),
    }

    key = (factor_signal, binary_cat)
    if key in matrix:
        adj, action, reasoning = matrix[key]
        return {"adjustment": adj, "action": action, "reasoning": reasoning}

    # Fallback
    return {"adjustment": 1.0, "action": "WEIGHT",
            "reasoning": f"未定義の組み合わせ factor={factor_signal} binary={binary_cat} → 目標ウェイト維持"}


def main():
    parser = argparse.ArgumentParser(
        description="ポートフォリオポジションに基づく個別トレードアドバイス"
    )
    parser.add_argument("--ticker", help="TSEティッカーシンボル (例: 7203.T)")
    parser.add_argument("--portfolio", help="portfolio.yaml のパス (ポートフォリオ全体分析)")
    parser.add_argument("--cost-basis", type=float, help="1株あたりの取得単価 (円)")
    parser.add_argument("--shares", type=int, help="保有株式数")
    parser.add_argument("--mode", default="spot", choices=["spot", "margin"],
                        help="ポジション種別 (default: spot)")
    parser.add_argument("--target-years", default=1, type=int,
                        help="バックテスト期間 (年数, default: 1)")
    parser.add_argument("--portfolio-value", type=float,
                        help="ポートフォリオ評価額合計 (円)")
    parser.add_argument("--output", "-o", help="JSON出力ファイルパス")
    parser.add_argument("--date", help="基準日 YYYY-MM-DD (default: 直近取引日)")
    parser.add_argument("--backtest-result", help="Pre-computed backtest result JSON (skips live backtest)")
    parser.add_argument("--factor-mode", action="store_true",
                        help="ファクタースコアを計算し仲裁マトリクスを適用")
    args = parser.parse_args()

    # --portfolio mode: compute inverse-vol weights for all positions
    if args.portfolio:
        portfolio_data = _load_portfolio_yaml(args.portfolio)
        holdings = portfolio_data.get("holdings", [])
        account = portfolio_data.get("account", {})
        total_assets = account.get("total_assets", 0) or args.portfolio_value or 0

        positions = []
        for h in holdings:
            positions.append({
                "ticker": h["ticker"],
                "market_price": h.get("current_price", 0),
                "shares": h.get("quantity", 0),
                "mode": "margin" if h.get("position_type") == "信用" else "spot",
            })

        result = compute_inverse_vol_weights(positions, total_assets)
        result["analysis_date"] = args.date or get_latest_trading_day()
        result["total_assets"] = total_assets
        result["available_cash"] = account.get("available_cash", 0)
        result["num_positions"] = len(positions)
        result["margin_positions_excluded"] = (
            "Margin positions use existing backtest_engine margin logic independently. "
            "Not included in inverse-vol sizing."
        )
        _output_result(result, args.output)
        return

    # --ticker mode: per-ticker advisory (existing behavior)
    if not args.ticker or args.cost_basis is None or args.shares is None:
        parser.error("--ticker, --cost-basis, --shares が必要です (または --portfolio で全体分析)")

    # Resolve analysis date with fallback for missing indicator data
    date_str = args.date or get_latest_trading_day()
    analysis = None
    for attempt in range(5):
        analysis = analyze_ticker(args.ticker, date_str)
        if "error" not in analysis and analysis.get("trend_state") != "unknown":
            break
        if attempt < 4:
            date_str = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    try:
        # 1. Get current market price
        market_price = fetch_market_price(args.ticker)

        # 2. Compute P&L
        pnl, pnl_pct = compute_pnl(market_price, args.cost_basis, args.shares)
        if "error" in analysis:
            result = {
                "ticker": args.ticker,
                "analysis_date": date_str,
                "error": f"Signal engine error: {analysis['error']}",
            }
            _output_result(result, args.output)
            return

        # 4. Run backtest for signal win rates
        bt_result = None
        if args.backtest_result and os.path.exists(args.backtest_result):
            with open(args.backtest_result) as f:
                bt_result = json.load(f)
        per_rule, active_rules, max_holding_days = run_backtest_win_rates(
            args.ticker, date_str, args.target_years,
            backtest_result=bt_result,
        )

        signal_win_rates = {
            "active_signals": active_rules,
            "per_rule": per_rule or {},
        }

        # 4.5. Check signal conformation (2 of last 3 days)
        conformation = check_signal_conformation(args.ticker, date_str, active_rules)
        for s in active_rules:
            rule_name = s.get("rule", "")
            if rule_name in conformation:
                conf = conformation[rule_name]
                if not conf["conformed"]:
                    if "caveat" not in s:
                        s["caveat"] = "signal_not_confirmed"
                    s["conformation"] = conf
                else:
                    s["conformation"] = conf
        if conformation:
            signal_win_rates["signal_conformation"] = conformation

        # 5. Compute advisory
        advisory = compute_advisory(
            analysis["score"],
            analysis["trend_state"],
            pnl_pct,
            signal_win_rates,
        )

        # 6. Target prices
        targets = compute_target_prices(
            analysis.get("indicators", {}),
            analysis.get("analyst", {}),
            market_price,
            advisory["opinion"],
        )
        advisory.update(targets)
        advisory["max_holding_days"] = max_holding_days

        # 7. Risk assessment
        atr_val = _safe_float(analysis.get("indicators", {}).get("atr"))
        risk = assess_risk(
            market_price, args.shares, args.mode,
            args.portfolio_value, analysis.get("indicators", {}),
            analysis.get("signals", []), atr_val,
        )

        # Factor mode: compute factor scores and apply arbitration
        factor_arbitration = None
        if args.factor_mode:
            try:
                from factor_engine import compute_factors, classify_factor_signal
                factor_result = compute_factors(args.ticker)
                factor_signal = classify_factor_signal(factor_result.get("composite_z"))
                factor_arbitration = arbitrate_factor_vs_rule(
                    factor_signal, advisory["opinion"])
                factor_arbitration["factor_scores"] = factor_result
                factor_arbitration["factor_signal"] = factor_signal
            except Exception as e:
                factor_arbitration = {"error": str(e)}

        # Build output
        result = {
            "ticker": args.ticker,
            "analysis_date": date_str,
            "position": {
                "market_price": market_price,
                "cost_basis": args.cost_basis,
                "shares": args.shares,
                "market_value": market_price * args.shares,
                "unrealized_pnl": pnl,
                "unrealized_pnl_pct": pnl_pct,
                "mode": args.mode,
            },
            "current_signals": analysis.get("signals", []),
            "trend_state": analysis.get("trend_state"),
            "overall_score": analysis.get("score"),
            "analyst_targets": analysis.get("analyst", {}),
            "signal_win_rates": signal_win_rates,
            "advisory": advisory,
            "risk_assessment": risk,
        }
        if factor_arbitration:
            result["factor_arbitration"] = factor_arbitration

        _output_result(result, args.output)

    except Exception as e:
        logger.exception("Trade advisor failed")
        result = {
            "ticker": args.ticker,
            "analysis_date": date_str,
            "error": str(e),
        }
        _output_result(result, args.output)
        sys.exit(1)


def _output_result(result: dict, output_path: str):
    output_json = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as f:
            f.write(output_json)
        print(f"Output written to {output_path}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
