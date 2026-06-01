"""Build a deterministic report_context.json from all pipeline artifacts.

Usage:
    python report_context_builder.py \
        --portfolio path/to/portfolio.yaml \
        --signals path/to/signals.json \
        --backtest-dir path/to/backtest/ \
        --portfolio-analytics path/to/portfolio_analytics.json \
        --quant-decisions path/to/quant_decisions.json \
        -o output/report_context.json
"""

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yaml
from strategy_review import summarize_strategy_review
from frequency_research import summarize_frequency_diagnostics, normalize_frequency_diagnostics


class DateAwareEncoder(json.JSONEncoder):
    """JSON encoder that handles datetime.date objects by converting to ISO strings."""
    def default(self, o):
        if isinstance(o, datetime.date):
            return o.isoformat()
        return super().default(o)


def build_macro_context(signals_data: dict) -> dict:
    if signals_data.get("macro_context"):
        return signals_data["macro_context"]
    for entry in signals_data.get("results", []):
        macro = entry.get("macro")
        if isinstance(macro, dict) and macro:
            return macro
    return {}


def load_portfolio(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def build_account(portfolio: dict) -> dict:
    acct = portfolio.get("account", {})
    margin_ratio = acct.get("margin_ratio", 0)
    return {
        "total_assets": acct.get("total_assets", 0),
        "available_cash": acct.get("available_cash", 0),
        "margin_ratio": margin_ratio,
        "margin_ratio_label": "委託保証金率",
        "margin_ratio_text": f"{margin_ratio:.2f}%",
    }


def build_holdings(portfolio: dict) -> list[dict]:
    return portfolio.get("holdings", [])


def build_watchlist(portfolio: dict) -> list[dict]:
    return portfolio.get("watchlist", [])


def build_signals(signals_data: dict) -> dict[str, dict]:
    """Build per-ticker signal info, preserving exact rule names."""
    result = {}
    for entry in signals_data.get("results", []):
        ticker = entry["ticker"]
        result[ticker] = {
            "score": entry.get("score", {}),
            "signals": [
                {"type": s["type"], "rule": s["rule"], "strength": s["strength"]}
                for s in entry.get("signals", [])
            ],
            "indicators": entry.get("indicators", {}),
        }
    return result


def build_backtest_results(backtest_dir: str) -> dict[str, dict]:
    """Load backtest JSON files, preserving walk_forward verdict as-is."""
    results = {}
    if not os.path.isdir(backtest_dir):
        return results
    for fname in os.listdir(backtest_dir):
        if not fname.endswith(".json"):
            continue
        ticker = fname[: -len(".json")]
        path = os.path.join(backtest_dir, fname)
        with open(path) as f:
            data = json.load(f)
        entry = {"baseline": data.get("baseline", {})}
        wf = data.get("walk_forward", {})
        entry["walk_forward"] = {
            "overfit_detected": wf.get("overfit_detected", False),
            "verdict": wf.get("consensus", {}).get("verdict", "unknown"),
            "consensus": wf.get("consensus", {}),
            "data_quality": wf.get("data_quality") or wf.get("consensus", {}).get("data_quality", ""),
        }
        # Preserve strategy gate metadata when present
        if "strategy_selection" in data:
            entry["strategy_selection"] = data["strategy_selection"]
        if "benchmark_comparison" in data:
            entry["benchmark_comparison"] = data["benchmark_comparison"]
        if "strategy_comparison" in data:
            entry["strategy_comparison"] = data["strategy_comparison"]
        results[ticker] = entry
    return results


def build_portfolio_analytics(analytics_data: dict) -> dict:
    return analytics_data.get("correlation", {})


def build_quant_decisions(decisions_data: dict) -> dict[str, dict]:
    """Build per-ticker decisions, mapping action directly as report_action."""
    result = {
        "generated_at": decisions_data.get("generated_at"),
        "decisions": {},
    }
    for d in decisions_data.get("decisions", []):
        ticker = d["ticker"]
        result["decisions"][ticker] = {
            "report_action": d["action"],
            "confidence": d["confidence"],
            "order_shares": d["order_shares"],
            "order_type": d["order_type"],
            "limit_price": d["limit_price"],
            "vetoes": d.get("vetoes", []),
            "risk_flags": d.get("risk_flags", []),
            "explanations": d.get("explanations", []),
            "risk_posture": d.get("risk_posture", "neutral"),
            "protective_stop_price": d.get("protective_stop_price"),
            "portfolio_weight_pct": d.get("portfolio_weight_pct"),
            "cost_basis_weight_pct": d.get("cost_basis_weight_pct"),
            "unrealized_pnl_pct": d.get("unrealized_pnl_pct"),
            "downside_10pct_yen": d.get("downside_10pct_yen"),
            "advisory_plan": d.get("advisory_plan", {}),
        }
    return result


def build_context(
    portfolio_path: str,
    signals_path: str,
    backtest_dir: str,
    analytics_path: str,
    decisions_path: str,
    strategy_risk_mode: str = "balanced",
) -> dict:
    portfolio = load_portfolio(portfolio_path)
    signals_data = load_json(signals_path)
    analytics_data = load_json(analytics_path)
    decisions_data = load_json(decisions_path)

    account = build_account(portfolio)
    quote_map = {}
    for entry in signals_data.get("results", []):
        t = entry.get("ticker")
        if t:
            quote_map[t] = entry.get("quote", {})
    holdings = []
    stale_tickers = []
    for h in build_holdings(portfolio):
        item = dict(h)
        q = quote_map.get(item.get("ticker"), {})
        item["portfolio_price"] = item.get("current_price")
        if q.get("price") is not None and not q.get("is_stale"):
            item["current_price"] = q["price"]
            item["price_source"] = q.get("source", "")
            item["price_as_of"] = q.get("as_of")
        else:
            item["price_source"] = q.get("source", "portfolio_yaml")
            item["price_as_of"] = q.get("as_of")
            if q.get("is_stale"):
                stale_tickers.append(item.get("ticker"))
        holdings.append(item)
    price_freshness = {"stale_count": len(set(stale_tickers)), "stale_tickers": sorted(set(stale_tickers))}
    watchlist = build_watchlist(portfolio)
    signals = build_signals(signals_data)
    backtest = build_backtest_results(backtest_dir)
    correlations = build_portfolio_analytics(analytics_data)
    quant = build_quant_decisions(decisions_data)

    return {
        "reference_date": signals_data.get("reference_date", ""),
        "account": account,
        "holdings": holdings,
        "watchlist": watchlist,
        "signals": signals,
        "backtest": backtest,
        "strategy_review": summarize_strategy_review(backtest, risk_mode=strategy_risk_mode),
        "strategy_risk_mode": strategy_risk_mode,
        "correlations": correlations,
        "quant_decisions": quant,
        "macro_context": build_macro_context(signals_data),
        "frequency_diagnostics": normalize_frequency_diagnostics(
            summarize_frequency_diagnostics(backtest),
            holdings_count=len(holdings),
            backtests=backtest,
        ),
        "price_freshness": price_freshness,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Build report_context.json from pipeline artifacts"
    )
    parser.add_argument("--portfolio", required=True)
    parser.add_argument("--signals", required=True)
    parser.add_argument("--backtest-dir", required=True)
    parser.add_argument("--portfolio-analytics", required=True)
    parser.add_argument("--quant-decisions", required=True)
    parser.add_argument("-o", "--output", required=True)
    parser.add_argument("--strategy-risk-mode", choices=["defensive", "balanced", "aggressive"],
                        default="balanced", help="Risk mode for strategy review")
    args = parser.parse_args()

    context = build_context(
        portfolio_path=args.portfolio,
        signals_path=args.signals,
        backtest_dir=args.backtest_dir,
        analytics_path=args.portfolio_analytics,
        strategy_risk_mode=args.strategy_risk_mode,
        decisions_path=args.quant_decisions,
    )

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(context, f, ensure_ascii=False, indent=2, cls=DateAwareEncoder)
    print(f"Report context written to {args.output}")


if __name__ == "__main__":
    main()
