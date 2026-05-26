#!/usr/bin/env python3
"""Signal efficacy tracker — monitors out-of-sample performance per rule.

Tracks each signal rule's Sharpe ratio over rolling 6-month windows.
Auto-downgrades rules with negative rolling Sharpe, with hysteresis
requiring 2 consecutive positive windows for re-enablement.

Usage:
    python signal_efficacy.py --ticker 1515.T
    python signal_efficacy.py --ticker 1515.T --output /tmp/efficacy.json
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from signal_engine import get_latest_trading_day
from backtest_engine import generate_signals, simulate_trades

WINDOW_MONTHS = 6
POSITIVE_WINDOWS_FOR_REENABLE = 2
MIN_TRADES_FOR_EFFICACY = 5


def _sharpe_from_returns(returns: list) -> float:
    """Compute annualized Sharpe ratio from a list of fractional returns."""
    if len(returns) < 2:
        return 0.0
    avg = sum(returns) / len(returns)
    if avg == 0:
        return 0.0
    var = sum((r - avg) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    if std == 0:
        return 0.0
    return (avg / std) * math.sqrt(252)


def track_efficacy(ticker: str, end_date: str, lookback_years: float = 3.0):
    """Compute per-rule rolling efficacy over the lookback period.

    Returns a dict with per-rule status and rolling window history.
    """
    start_dt = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(
        days=int(365.25 * lookback_years)
    )
    start_date = start_dt.strftime("%Y-%m-%d")

    sig_df = generate_signals(ticker, start_date, end_date)
    metrics = simulate_trades(sig_df, ticker=ticker)
    trades = metrics.get("trades", [])

    if not trades:
        return {"ticker": ticker, "status": "no_data", "rules": {}}

    # Collect trades by rule
    rule_trades = {}
    for t in trades:
        rule = t.get("entry_signal_rule")
        if not rule:
            continue
        if rule not in rule_trades:
            rule_trades[rule] = []
        rule_trades[rule].append(t)

    # Generate rolling 6-month windows, shifted by 1 month
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    rules = {}

    for rule, rt in rule_trades.items():
        total_trades = len(rt)
        rolling_windows = []

        # Slide windows back from end_date
        window_end = end_dt
        while window_end > start_dt:
            window_start = window_end - timedelta(days=int(365.25 * WINDOW_MONTHS / 12))
            window_start_str = window_start.strftime("%Y-%m-%d")
            window_end_str = window_end.strftime("%Y-%m-%d")

            window_returns = [
                t["return"]
                for t in rt
                if window_start_str <= t["exit_date"] <= window_end_str
            ]
            win_sharpe = _sharpe_from_returns(window_returns)
            rolling_windows.append({
                "window_start": window_start_str,
                "window_end": window_end_str,
                "trade_count": len(window_returns),
                "sharpe": round(win_sharpe, 4),
            })
            window_end -= timedelta(days=30)  # slide back 1 month

        # Status determination
        recent_windows = rolling_windows[:POSITIVE_WINDOWS_FOR_REENABLE + 1]

        if total_trades < MIN_TRADES_FOR_EFFICACY:
            status = "insufficient_data"
            status_detail = f"取引数 {total_trades} < {MIN_TRADES_FOR_EFFICACY}、信頼性判断不可"
        elif len(recent_windows) < 2:
            status = "insufficient_data"
            status_detail = "十分なローリングウィンドウデータなし"
        else:
            current_sharpe = recent_windows[0]["sharpe"]
            if current_sharpe >= 0:
                status = "active"
                status_detail = f"直近ウィンドウ Sharpe {current_sharpe:.3f}"
            else:
                # Check if signal was already degraded and look for re-enablement
                prev_positive = sum(
                    1 for w in recent_windows[1:POSITIVE_WINDOWS_FOR_REENABLE + 1]
                    if w["sharpe"] >= 0
                )
                if prev_positive >= POSITIVE_WINDOWS_FOR_REENABLE:
                    status = "active"
                    status_detail = (
                        f"再有効化: {POSITIVE_WINDOWS_FOR_REENABLE}連続陽性ウィンドウ検出"
                    )
                else:
                    status = "degraded"
                    status_detail = (
                        f"直近6ヶ月 Sharpe {current_sharpe:.3f} < 0、"
                        f"陽性回復まであと {POSITIVE_WINDOWS_FOR_REENABLE - prev_positive} ウィンドウ"
                    )

        rules[rule] = {
            "status": status,
            "status_detail": status_detail,
            "total_trades": total_trades,
            "rolling_windows": rolling_windows,
        }

    overall = _overall_status(rules)
    return {
        "ticker": ticker,
        "analysis_date": end_date,
        "status": overall["status"],
        "status_message": overall["message"],
        "rules": rules,
    }


def _overall_status(rules: dict) -> dict:
    """Compute overall efficacy status across all rules."""
    degraded = [r for r, info in rules.items() if info["status"] == "degraded"]
    active = [r for r, info in rules.items() if info["status"] == "active"]
    insufficient = [r for r, info in rules.items() if info["status"] == "insufficient_data"]

    messages = []
    if degraded:
        messages.append(
            f"劣化シグナル: {', '.join(degraded)} — "
            f"直近6ヶ月のローリングSharpeが負"
        )
    if active:
        messages.append(f"有効シグナル: {', '.join(active)}")
    if insufficient:
        messages.append(
            f"データ不足: {', '.join(insufficient)} "
            f"(取引数 < {MIN_TRADES_FOR_EFFICACY} またはウィンドウ不足)"
        )

    if degraded and not active:
        status = "degraded"
    elif degraded:
        status = "mixed"
    elif active:
        status = "healthy"
    else:
        status = "insufficient_data"

    return {"status": status, "message": "; ".join(messages) if messages else "判定不能"}


def main():
    parser = argparse.ArgumentParser(
        description="Signal efficacy tracker — rolling OOS Sharpe per rule"
    )
    parser.add_argument("--ticker", required=True, help="Ticker to analyze")
    parser.add_argument("--end", help="End date YYYY-MM-DD (default: latest trading day)")
    parser.add_argument("--lookback", type=float, default=3.0,
                        help="Lookback period in years (default: 3)")
    parser.add_argument("--output", "-o", help="Output JSON file path")
    args = parser.parse_args()

    end_date = args.end
    if not end_date:
        end_date = get_latest_trading_day()

    result = track_efficacy(args.ticker, end_date, lookback_years=args.lookback)

    output_json = json.dumps(result, ensure_ascii=False, indent=2, default=str)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Output written to {args.output}")

    # Print human-readable summary
    print(f"\n=== シグナル有効性: {args.ticker} ({end_date}) ===")
    print(f"全体ステータス: {result['status']} — {result['status_message']}")
    print()
    for rule_name, info in sorted(result["rules"].items()):
        status_label = {
            "active": "有効",
            "degraded": "劣化",
            "insufficient_data": "データ不足",
        }.get(info["status"], info["status"])
        print(f"  {rule_name}: {status_label} (取引数: {info['total_trades']})")
        print(f"    {info['status_detail']}")
        # Show last 2 windows for context
        windows = info.get("rolling_windows", [])
        if windows:
            recent = windows[:2]
            for w in recent:
                print(f"    [{w['window_start']} ~ {w['window_end']}] "
                      f"Sharpe={w['sharpe']:.3f}, trades={w['trade_count']}")

    print(output_json)


if __name__ == "__main__":
    main()
