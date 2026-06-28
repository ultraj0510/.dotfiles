#!/usr/bin/env python3
"""Daily portfolio runner. Runs stock-company-analyze for all holdings."""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

from analysis_v2_adapter import read_analysis_v2
from portfolio_helper import merge_portfolio_context

JST = timezone(timedelta(hours=9))
DEFAULT_DATA_DIR = Path("/Users/fujie/code/runtime/stock-company-analysis")
STOCK_COMPANY_ANALYZE = Path(
    "/Users/fujie/.dotfiles/claude/skills/stock-company-analyze/scripts/stock_company_analyze"
)


def collect_tickers(portfolio_path: Path) -> list[str]:
    """Return unique tickers from portfolio holdings (without .T suffix)."""
    portfolio = yaml.safe_load(portfolio_path.read_text()) or {}
    seen: dict[str, None] = {}
    for h in portfolio.get("holdings", []):
        t = h.get("ticker", "").replace(".T", "")
        if t:
            seen[t] = None
    return sorted(seen)


def run_analysis(ticker: str, data_dir: Path, skip_fundamental: bool = False) -> Path | None:
    """Run stock-company-analyze for a ticker. Returns path to analysis.json or None."""
    ticker_dir = data_dir / ticker

    # Check if recent analysis exists (skip if within 24h and --skip-fundamental)
    if skip_fundamental:
        latest_path = ticker_dir / "latest.json"
        if latest_path.exists():
            try:
                latest = json.loads(latest_path.read_text())
                updated = datetime.fromisoformat(latest["updated_at"])
                age = datetime.now(JST) - updated
                if age < timedelta(hours=24):
                    run_id = latest.get("latest_run_id")
                    if run_id:
                        analysis_path = ticker_dir / "runs" / run_id / "analysis.json"
                        if analysis_path.exists():
                            return analysis_path
            except Exception:
                pass

    # Record previous run_id to detect staleness
    prev_run_id = None
    prev_latest_path = ticker_dir / "latest.json"
    if prev_latest_path.exists():
        try:
            prev = json.loads(prev_latest_path.read_text())
            prev_run_id = prev.get("latest_run_id")
        except Exception:
            pass

    # Run analysis via stock_company_analyze wrapper
    cmd = [
        str(STOCK_COMPANY_ANALYZE),
        ticker,
        "--data-dir", str(data_dir),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            print(f"[WARN] {ticker}: analysis exited with code {result.returncode}",
                  file=sys.stderr)
            if result.stderr:
                print(f"  stderr: {result.stderr[:200]}", file=sys.stderr)
            return None
    except subprocess.TimeoutExpired:
        print(f"[WARN] {ticker}: analysis timed out", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[ERROR] {ticker}: {e}", file=sys.stderr)
        return None

    # Read latest.json — verify run_id changed
    latest_path = ticker_dir / "latest.json"
    if not latest_path.exists():
        return None
    try:
        latest = json.loads(latest_path.read_text())
        run_id = latest.get("latest_run_id")
        if run_id and run_id != prev_run_id:
            analysis_path = ticker_dir / "runs" / run_id / "analysis.json"
            if analysis_path.exists():
                return analysis_path
        elif run_id == prev_run_id:
            print(f"[WARN] {ticker}: analysis did not update latest.json",
                  file=sys.stderr)
    except Exception:
        pass
    return None


def build_daily_actions(portfolio_path: Path, data_dir: Path,
                        skip_fundamental: bool = False) -> dict:
    """Run analysis for all portfolio tickers and build daily_actions.json."""
    portfolio = yaml.safe_load(portfolio_path.read_text()) or {}
    tickers = collect_tickers(portfolio_path)

    actions = []
    for ticker in tickers:
        print(f"[INFO] Analyzing {ticker}...", file=sys.stderr)
        analysis_path = run_analysis(ticker, data_dir, skip_fundamental)
        if analysis_path is None:
            print(f"[WARN] {ticker}: no analysis.json produced", file=sys.stderr)
            continue
        try:
            analysis = read_analysis_v2(analysis_path)
            entry = merge_portfolio_context(portfolio, analysis)
            actions.append(entry)
        except Exception as e:
            print(f"[ERROR] {ticker}: failed to process analysis: {e}", file=sys.stderr)

    # Build summary
    action_needed = [
        {"ticker": a["ticker"], "today_action": a["today_action"],
         "reason": a.get("override_reason") or a["analysis"]["reasoning"][:60]}
        for a in actions if a["today_action"] != "NO_TRADE"
    ]
    monitor = [
        a["ticker"] for a in actions
        if a["today_action"] == "NO_TRADE" and a["analysis"]["execution_posture"] == "WAIT"
    ]
    reduce_candidates = [
        a["ticker"] for a in actions
        if a["analysis"]["investment_rating"] == "SELL" or a["today_action"] == "REDUCE"
    ]
    buy_candidates = [
        a["ticker"] for a in actions
        if a["analysis"]["investment_rating"] == "BUY" and a["today_action"] == "ACT_NOW"
    ]

    return {
        "generated_at": datetime.now(JST).isoformat(),
        "account": portfolio.get("account", {}),
        "actions": actions,
        "summary": {
            "total_positions": sum(len(a["holdings"]) for a in actions),
            "action_needed": action_needed,
            "monitor": monitor,
            "reduce_candidates": reduce_candidates,
            "buy_candidates": buy_candidates,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Daily portfolio action runner")
    parser.add_argument("--portfolio", required=True, help="Path to portfolio.yaml")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output", type=Path, help="Output path for daily_actions.json")
    parser.add_argument("--skip-fundamental", action="store_true",
                        help="Reuse recent analysis.json (<24h old)")
    args = parser.parse_args()

    result = build_daily_actions(
        Path(args.portfolio), args.data_dir, args.skip_fundamental
    )

    output_path = args.output or Path(args.portfolio).parent / "daily_actions.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"[INFO] Wrote daily_actions.json to {output_path}", file=sys.stderr)

    # Print summary
    s = result["summary"]
    print(f"\nTotal: {s['total_positions']} positions")
    print(f"Action needed: {len(s['action_needed'])}")
    for a in s["action_needed"]:
        print(f"  {a['ticker']}: {a['today_action']} — {a['reason']}")
    print(f"Monitor: {', '.join(s['monitor']) or 'none'}")
    print(f"Reduce candidates: {', '.join(s['reduce_candidates']) or 'none'}")

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
