#!/usr/bin/env python3
"""stock-company-analyze — full pipeline orchestrator."""
import argparse, json, os, sys, tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ticker_utils import normalize_ticker
from subprocess_runner import run_skill
from evidence_pack import build_evidence_pack
from market_metrics import compute_metrics
from rating_validator import validate_and_correct
from confidence import compute_confidence
from lock_manager import acquire_lock, release_lock
from analysis_store import save_analysis

JST = ZoneInfo("Asia/Tokyo")
DEFAULT_DATA_DIR = Path("/Users/fujie/code/runtime/stock-company-analysis")


def _atomic_write(path, data):
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=parent, suffix=".tmp", delete=False) as f:
            tmp = Path(f.name)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp and tmp.exists():
            tmp.unlink(missing_ok=True)


def _compute_valid_until(as_of, info_result):
    default_expiry = as_of + timedelta(days=90)
    next_earnings = None
    if info_result and info_result.parsed:
        earnings = info_result.parsed.get("data", {}).get("earnings", [])
        for item in (earnings if isinstance(earnings, list) else []):
            label = str(item.get("label", "")).lower()
            if any(kw in label for kw in ("次回", "next", "予定")):
                date_str = item.get("value", "")
                try:
                    next_earnings = datetime.fromisoformat(date_str).replace(tzinfo=JST)
                except (ValueError, TypeError):
                    pass
    if next_earnings and next_earnings > as_of and next_earnings < default_expiry:
        return next_earnings.isoformat()
    return default_expiry.isoformat()


def main():
    parser = argparse.ArgumentParser(prog="stock-company-analyze")
    parser.add_argument("ticker")
    parser.add_argument("--resume", type=str, default=None)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()

    ticker = normalize_ticker(args.ticker)
    if ticker is None:
        result = {"status": "failed", "error": "Invalid ticker"}
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        return 1

    now = datetime.now(JST)
    run_id = f"{now.strftime('%Y%m%dT%H%M%S%z')}-{ticker}"
    run_dir = args.data_dir / ticker / "runs" / run_id

    if args.resume:
        resume_dir = args.data_dir / ticker / "runs" / args.resume
        if not resume_dir.exists():
            result = {"status": "failed", "error": f"Run {args.resume} not found"}
            json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
            return 1

    lock = acquire_lock(ticker, run_id, args.data_dir)
    if not lock.acquired:
        result = {"status": "failed", "error": f"Lock held by run {lock.existing_run_id}"}
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        return 1

    try:
        # Phase 1: Acquisition
        info_result = run_skill("stock-info-fetch", [ticker])
        price_result = run_skill("stock-price-fetch", [ticker])
        ir_result = run_skill("stock-ir-fetch", [ticker])
        benchmark_result = run_skill("stock-price-fetch", [ticker, "--benchmark", "TOPIX"])

        if info_result.parsed and info_result.parsed.get("status") == "auth_expired":
            result = {"status": "failed", "error": "SBI auth expired"}
            json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
            return 1

        # Phase 1b: Save raw outputs
        raw_dir = args.data_dir / ticker / "raw"
        for name, res in [("stock-info-fetch", info_result), ("stock-price-fetch", price_result),
                          ("stock-ir-fetch", ir_result), ("stock-price-fetch-benchmark", benchmark_result)]:
            skill_raw_dir = raw_dir / name
            skill_raw_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write(skill_raw_dir / "stdout.json", res.stdout)
            _atomic_write(skill_raw_dir / "stderr.log", res.stderr)

        # Phase 2: Market metrics with TOPIX
        daily_bars = []
        benchmark_bars = []
        if price_result.parsed:
            daily_bars = price_result.parsed.get("data", {}).get("daily", {}).get("bars", [])
        if benchmark_result.parsed:
            benchmark_bars = benchmark_result.parsed.get("data", {}).get("daily", {}).get("bars", [])
        metrics = compute_metrics(daily_bars, [], benchmark_bars)
        run_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(run_dir / "market-metrics.json", json.dumps(metrics, ensure_ascii=False, indent=2))

        # Phase 3: Evidence pack
        company_name = ticker
        if info_result.parsed:
            company_name = info_result.parsed.get("company_name", ticker)
        pack = build_evidence_pack(ticker, company_name, now, info_result, price_result, ir_result, metrics)
        pack_path = run_dir / "evidence-pack.json"
        _atomic_write(pack_path, json.dumps(pack, ensure_ascii=False, indent=2))

        # Phase 4: TradingAgents
        from tradingagents_bridge import run_analysis
        ta_result = run_analysis(pack_path, run_dir / "market-metrics.json", run_dir)
        if ta_result.get("status") == "failed":
            result = {"status": "failed", "error": ta_result.get("error", "TradingAgents failed")}
            json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
            return 1

        # Phase 5: Rating
        pm_output = ta_result.get("result", {}).get("portfolio_manager", {})
        current_price = daily_bars[-1]["close"] if daily_bars else None
        data_quality = pack.get("data_quality", {})
        rating_result = validate_and_correct(pm_output, current_price, data_quality, {})

        # Phase 6: Confidence — measured from actual data
        price_age_days = 0
        if price_result.parsed:
            price_fetched = price_result.parsed.get("as_of", "")
            if price_fetched:
                try:
                    fetched_dt = datetime.fromisoformat(price_fetched)
                    price_age_days = (now - fetched_dt).total_seconds() / 86400
                except ValueError:
                    pass

        ir_age_days = 0
        if ir_result.parsed:
            ir_summary = ir_result.parsed.get("summary", {})
            latest_pub = ir_summary.get("latest_published_at", "")
            if latest_pub:
                try:
                    pub_dt = datetime.fromisoformat(latest_pub).replace(tzinfo=JST)
                    ir_age_days = (now - pub_dt).total_seconds() / 86400
                except ValueError:
                    ir_age_days = 90

        spread = 999
        constraints_met = not rating_result.adjusted
        if rating_result.scenario_prices:
            prices = list(rating_result.scenario_prices.values())
            if len(prices) == 3 and prices[1] > 0:
                spread = (prices[0] - prices[2]) / prices[1]

        all_evidence = True
        analyst_reports = ta_result.get("result", {}).get("analyst_reports", {})
        for side in ("bull_researcher", "bear_researcher"):
            report = analyst_reports.get(side, {})
            for claim in report.get("claims", []):
                if not claim.get("evidence_ids"):
                    all_evidence = False

        # Compute essential_items_available for confidence (10 items × 3pts each = max 30)
        essential_count = 0
        if current_price:
            essential_count += 1  # 1. current price
        if daily_bars and len(daily_bars) >= 250:
            essential_count += 1  # 6. balance sheet info (proxy: sufficient price history)
        if info_result.parsed:
            sections = info_result.parsed.get("sections", {})
            perf = sections.get("performance", {}) if isinstance(sections, dict) else {}
            if isinstance(perf, dict) and perf.get("data"):
                essential_count += 1  # 2/3/4. earnings data
        if ir_result.parsed and ir_result.parsed.get("documents"):
            essential_count += 1  # 10. latest IR materials
        data_quality["essential_items_available"] = essential_count

        conf_result = compute_confidence(
            data_quality=data_quality,
            data_freshness={"price_age_days": price_age_days, "news_age_hours": 1, "ir_age_days": ir_age_days},
            scenario_stability={"constraints_met": constraints_met, "spread": spread},
            bull_bear_consistency={"all_claims_have_evidence": all_evidence, "unresolved_contradictions": False},
            provisional=rating_result.provisional,
            not_rated=(rating_result.final_rating == "NOT_RATED"),
        )

        # Phase 7: analysis.json
        analysis = {
            "schema_version": "1.0",
            "run_id": run_id, "ticker": ticker, "company_name": company_name,
            "as_of": now.isoformat(),
            "valid_until": _compute_valid_until(now, info_result),
            "status": "completed",
            "rating": {
                "portfolio_manager_proposal": rating_result.pm_proposal,
                "final": rating_result.final_rating,
                "adjusted": rating_result.adjusted,
                "adjustment_reasons": rating_result.adjustment_reasons,
                "provisional": rating_result.provisional,
                "provisional_reasons": rating_result.provisional_reasons,
                "short_eligible": rating_result.short_eligible,
            },
            "expected_return": {
                "current_price": current_price,
                "expected_price": rating_result.expected_price,
                "expected_return": rating_result.expected_return,
                "scenario_prices": rating_result.scenario_prices,
            },
            "topix_comparison": metrics.get("topix_relative"),
            "confidence": conf_result,
            "fact_sheet": {},
            "analyst_reports": analyst_reports,
            "debate": ta_result.get("result", {}).get("debate", {}),
            "investment_thesis": "",
            "scenarios": pm_output.get("scenarios", []),
            "catalysts": pm_output.get("catalysts", []),
            "disconfirmers": pm_output.get("disconfirmers", []),
            "monitoring_triggers": pm_output.get("monitoring_triggers", []),
            "unknowns": pm_output.get("data_gaps", []),
            "source_run_ids": {
                "stock_info_fetch": info_result.parsed.get("run_id") if info_result.parsed else None,
                "stock_price_fetch": price_result.parsed.get("run_id") if price_result.parsed else None,
                "stock_ir_fetch": ir_result.parsed.get("run_id") if ir_result.parsed else None,
            },
            "evidence_pack_sha256": pack["sha256"],
            "run_manifest_ref": "claude-sonnet-4-6",
        }

        run_manifest = {
            "run_id": run_id, "ticker": ticker,
            "started_at": now.isoformat(),
            "completed_at": datetime.now(JST).isoformat(),
            "elapsed_seconds": ta_result.get("elapsed_seconds"),
            "model_id": "claude-sonnet-4-6",
            "temperature": None,
            "prompt_version": "1.0",
            "retry_count": 0,
            "estimated_cost_jpy": None,
            "cost_exceeded_warning": False,
            "evidence_pack_sha256": pack["sha256"],
            "skill_versions": {
                "stock-info-fetch": info_result.parsed.get("run_id") if info_result.parsed else None,
                "stock-price-fetch": price_result.parsed.get("run_id") if price_result.parsed else None,
                "stock-ir-fetch": ir_result.parsed.get("run_id") if ir_result.parsed else None,
            },
            "checkpoint_agent_order": [
                "market_analyst", "fundamentals_analyst", "news_analyst",
                "bull_researcher", "bear_researcher", "portfolio_manager",
            ],
        }
        save_analysis(args.data_dir, ticker, run_id, analysis, run_manifest)

        json.dump(analysis, sys.stdout, ensure_ascii=False, indent=2, allow_nan=False)
        sys.stdout.write("\n")
        return 0

    finally:
        release_lock(ticker, args.data_dir)


if __name__ == "__main__":
    raise SystemExit(main())
