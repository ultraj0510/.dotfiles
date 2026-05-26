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
import os
import signal
import sys
from datetime import datetime, timedelta

import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_utils import yf_retry, load_ohlcv
from signal_engine import analyze_ticker, get_latest_trading_day
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


def run_backtest_win_rates(ticker: str, date_str: str, target_years: int):
    """Run a backtest and compute per-rule signal win rates.

    Results are cached for 1 hour. Returns (per_rule, active_win_rates_list,
    max_holding_days) or (None, [], 0) on failure/timeout.
    """
    # Check cache first
    cached = _load_cache(ticker, target_years)
    if cached is not None:
        return cached

    end_dt = datetime.strptime(date_str, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=int(365.25 * target_years))
    start_date = start_dt.strftime("%Y-%m-%d")

    original_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(30)
    try:
        sig_df = generate_signals(ticker, start_date, date_str)
        metrics = simulate_trades(sig_df)
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


def main():
    parser = argparse.ArgumentParser(
        description="ポートフォリオポジションに基づく個別トレードアドバイス"
    )
    parser.add_argument("--ticker", required=True, help="TSEティッカーシンボル (例: 7203.T)")
    parser.add_argument("--cost-basis", required=True, type=float, help="1株あたりの取得単価 (円)")
    parser.add_argument("--shares", required=True, type=int, help="保有株式数")
    parser.add_argument("--mode", default="spot", choices=["spot", "margin"],
                        help="ポジション種別 (default: spot)")
    parser.add_argument("--target-years", default=1, type=int,
                        help="バックテスト期間 (年数, default: 1)")
    parser.add_argument("--portfolio-value", type=float,
                        help="ポートフォリオ評価額合計 (円)")
    parser.add_argument("--output", "-o", help="JSON出力ファイルパス")
    parser.add_argument("--date", help="基準日 YYYY-MM-DD (default: 直近取引日)")
    args = parser.parse_args()

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
        per_rule, active_rules, max_holding_days = run_backtest_win_rates(
            args.ticker, date_str, args.target_years,
        )

        signal_win_rates = {
            "active_signals": active_rules,
            "per_rule": per_rule or {},
        }

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
