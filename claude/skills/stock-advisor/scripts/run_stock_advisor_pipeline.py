#!/usr/bin/env python3
# DEPRECATED: Use run_daily_actions.py instead.
# This pipeline is kept for reference only and will be removed in a future phase.
# See: stock-advisor/scripts/run_daily_actions.py
"""Run the full stock-advisor pipeline end-to-end.

Steps:
  1. Signal engine (--all mode)
  2. Per-ticker backtest (with execution-delay, capped concurrency)
  3. Portfolio analytics
  4. Quant decisions
  5. Report context builder

Usage:
    python run_stock_advisor_pipeline.py \
        --portfolio portfolio.yaml --watchlist watchlist.yaml \
        --results-dir /tmp/results --date 2026-05-29
"""

import argparse
import json
import logging
import pathlib
import subprocess
import sys
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("pipeline")

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
VENV_PYTHON = SCRIPTS_DIR / ".venv" / "bin" / "python"

from market_clock import classify_market_session

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def collect_tickers(portfolio_path: pathlib.Path, watchlist_path: pathlib.Path) -> list[str]:
    """Return sorted unique tickers from portfolio holdings and watchlist."""
    import yaml

    portfolio = yaml.safe_load(portfolio_path.read_text()) or {}
    seen: dict[str, None] = {}
    for h in portfolio.get("holdings", []):
        t = h.get("ticker")
        if t:
            seen[t] = None
    if watchlist_path.exists():
        for item in yaml.safe_load(watchlist_path.read_text()) or []:
            if isinstance(item, dict) and item.get("ticker"):
                seen[item["ticker"]] = None
    return sorted(seen)


def read_reference_date(signals_path: pathlib.Path) -> str:
    """Extract reference_date from a signals.json file."""
    data = json.loads(signals_path.read_text())
    return data.get("reference_date", "")


def run(cmd: list[str]) -> None:
    """Print and execute a subprocess command."""
    log.info("+ %s", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stock-advisor pipeline runner")
    parser.add_argument("--portfolio", required=True, help="Path to portfolio.yaml")
    parser.add_argument("--watchlist", required=True, help="Path to watchlist.yaml")
    parser.add_argument("--results-dir", required=True, help="Output directory for artifacts")
    parser.add_argument("--date", default="", help="Reference date (YYYY-MM-DD), auto-detected from signals if empty")
    parser.add_argument("--strategy-risk-mode", choices=["defensive", "balanced", "aggressive"],
                        default="balanced", help="Risk mode for candidate strategy execution")
    parser.add_argument("--skip-wf-research", action="store_true",
                        help="Skip WF research comparison to reduce runtime")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    results_dir = pathlib.Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)

    portfolio_path = pathlib.Path(args.portfolio)
    watchlist_path = pathlib.Path(args.watchlist)

    # -- Step 1: Signal engine ---------------------------------------------------
    log.info("=== Step 1: Signal engine ===")
    signals_path = results_dir / "signals.json"
    market_session = classify_market_session()
    signal_cmd = [str(SCRIPTS_DIR / "run_signal_engine"), "--all", "--output", str(signals_path)]
    if market_session == "open":
        signal_cmd.append("--refresh")
    run(signal_cmd)

    # Detect reference date from signals output (or use CLI override)
    reference_date = args.date or read_reference_date(signals_path)
    if not reference_date:
        log.error("Could not determine reference_date; supply --date or check signals.json output")
        sys.exit(1)
    log.info("Reference date: %s", reference_date)

    # -- Step 2: Backtest per ticker ----------------------------------------------
    log.info("=== Step 2: Backtest per ticker ===")
    tickers = collect_tickers(portfolio_path, watchlist_path)
    if not tickers:
        log.warning("No tickers found; pipeline will be incomplete")
    backtest_dir = results_dir / "backtest"
    backtest_dir.mkdir(parents=True, exist_ok=True)

    for ticker in tickers:
        out_path = backtest_dir / f"{ticker}.json"
        backtest_cmd = [
            str(VENV_PYTHON), str(SCRIPTS_DIR / "backtest_engine.py"),
            "--ticker", ticker,
            "--strategy", "auto",
            "--execution-delay",
            "--end", reference_date,
            "-o", str(out_path),
        ]
        if not args.skip_wf_research:
            backtest_cmd.extend(["--wf-research", "--no-cache"])
        run(backtest_cmd)

    # -- Step 3: Portfolio analytics ----------------------------------------------
    log.info("=== Step 3: Portfolio analytics ===")
    analytics_path = results_dir / "portfolio_analytics.json"
    run([
        str(VENV_PYTHON), str(SCRIPTS_DIR / "portfolio_analytics.py"),
        "--portfolio", str(portfolio_path),
        "-o", str(analytics_path),
    ])

    # -- Step 4: Quant decisions ---------------------------------------------------
    log.info("=== Step 4: Quant decisions ===")
    decisions_path = results_dir / "quant_decisions.json"
    run([
        str(VENV_PYTHON), str(SCRIPTS_DIR / "quant_decision_engine.py"),
        "--portfolio", str(portfolio_path),
        "--signals", str(signals_path),
        "--backtest-dir", str(backtest_dir),
        "--portfolio-analytics", str(analytics_path),
        "--strategy-risk-mode", args.strategy_risk_mode,
        "-o", str(decisions_path),
    ])

    # -- Step 5: Report context ----------------------------------------------------
    log.info("=== Step 5: Report context ===")
    context_path = results_dir / "report_context.json"
    run([
        str(VENV_PYTHON), str(SCRIPTS_DIR / "report_context_builder.py"),
        "--portfolio", str(portfolio_path),
        "--signals", str(signals_path),
        "--backtest-dir", str(backtest_dir),
        "--portfolio-analytics", str(analytics_path),
        "--quant-decisions", str(decisions_path),
        "--strategy-risk-mode", args.strategy_risk_mode,
        "-o", str(context_path),
    ])

    # -- Step 6: HTML report --------------------------------------------------------
    log.info("=== Step 6: HTML report ===")
    html_report_path = results_dir / "report.html"
    run([
        str(VENV_PYTHON), str(SCRIPTS_DIR / "html_report_builder.py"),
        "--context", str(context_path),
        "-o", str(html_report_path),
    ])

    # -- Manifest -----------------------------------------------------------------
    price_freshness = {}
    if context_path.exists():
        ctx_data = json.loads(context_path.read_text())
        price_freshness = ctx_data.get("price_freshness", {})
    manifest = {
        "generated_at": datetime.now().isoformat(),
        "results_dir": str(results_dir),
        "reference_date": reference_date,
        "strategy_risk_mode": args.strategy_risk_mode,
        "market_session": market_session,
        "price_freshness": price_freshness,
        "settings": {"wf_research": not args.skip_wf_research},
        "tickers": tickers,
        "artifacts": {
            "signals": str(signals_path),
            "backtest_dir": str(backtest_dir),
            "portfolio_analytics": str(analytics_path),
            "quant_decisions": str(decisions_path),
            "report_context": str(context_path),
            "html_report": str(html_report_path),
        },
    }
    manifest_path = results_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    log.info("Manifest written to %s", manifest_path)
    log.info("Pipeline complete.")


if __name__ == "__main__":
    main()
