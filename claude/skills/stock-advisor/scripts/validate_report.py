#!/usr/bin/env python3
"""Validate a generated stock report against known artifacts.

Usage:
    validate_report.py --report <path> --signals <path> --quant-decisions <path> --backtest-dir <path>

Checks:
  1. Invented signal names -- any lowercase underscored token not in known signal rules
  2. Quant action override  -- SELL/REDUCE tickers must have matching Japanese action words
  3. Wrong account label    -- "信用倍率" (must be "委託保証金率")
  4. Inflated walk-forward  -- "robust" in report but any ticker has non-robust verdict

Exit 0 on clean, exit 1 with message on violation.
"""
import argparse
import json
import os
import re
import sys
import yaml

KNOWN_METADATA_TOKENS = {
    "open_date", "expiry_date", "quant_decisions", "report_context",
    "risk_posture", "advisory_plan", "protective_stop_price",
    "portfolio_weight_pct", "cost_basis_weight_pct", "unrealized_pnl_pct",
    "downside_10pct_yen", "report_action", "order_shares", "order_type", "limit_price",
    # Trend states (from signal_engine trend_state field)
    "strong_uptrend", "strong_downtrend", "downtrend", "ranging",
    "uptrend",
    # Walk-forward data quality / stability fields
    "thin_oos_trades", "no_oos_trades", "sufficient_oos_trades",
    "insufficient_price_history", "overfit_majority", "some_overfit",
    "thin_sample", "not_evaluable", "low_dispersion", "moderate_dispersion",
    "limited", "total_test_trades", "valid_test_windows", "data_quality",
    "stability_flag", "data_insufficient",
    # Strategy gate tokens
    "hold_baseline", "too_few_strategy_trades", "no_strategy_passed_tradeability_gate",
    "strategy_underperforms_benchmark", "strategy_not_tradeable",
    "strategy_beats_benchmark", "strategy_improves_risk_adjusted_return",
    "strategy_selection", "benchmark_comparison", "selected_strategy",
    "strategy_total_return", "benchmark_total_return", "excess_total_return",
    "strategy_sharpe", "benchmark_sharpe", "excess_sharpe",
    "strategy_max_drawdown", "benchmark_max_drawdown", "drawdown_not_worse",
    "beats_benchmark_return", "beats_benchmark_sharpe",
    "strategy_comparison",
    # Default strategy names
    "trend", "contrarian", "default", "balanced_frequency",
}


def _known_signal_rules(signals_path: str) -> set[str]:
    """Collect all unique signal rule names from signals.json."""
    with open(signals_path) as f:
        data = json.load(f)
    rules: set[str] = set()
    for result in data.get("results", []):
        for signal in result.get("signals", []):
            rule = signal.get("rule")
            if rule:
                rules.add(rule)
    return rules


def _underscore_tokens(text: str) -> list[str]:
    """Find all lowercase tokens containing at least one underscore."""
    return re.findall(r"\b[a-z]+[a-z0-9]*(?:_[a-z0-9]+)+\b", text)


def check_invented_signals(report_text: str, signals_path: str, quant_decisions_path: str, backtest_dir: str = "") -> str | None:
    """Return an error message if the report invents a signal name, else None."""
    known = _known_signal_rules(signals_path)
    known.update(KNOWN_METADATA_TOKENS)
    # Also allow veto and risk_flag names from quant_decisions
    with open(quant_decisions_path) as f:
        qd = json.load(f)
    for d in qd.get("decisions", []):
        for v in d.get("vetoes", []):
            known.add(v)
        for v in d.get("risk_flags", []):
            known.add(v)
    # Also allow WF verdict terms from backtest dir
    if backtest_dir and os.path.isdir(backtest_dir):
        for fname in os.listdir(backtest_dir):
            if fname.endswith(".json"):
                with open(os.path.join(backtest_dir, fname)) as f:
                    data = json.load(f)
                v = data.get("walk_forward", {}).get("consensus", {}).get("verdict", "")
                if v:
                    known.add(v)
    tokens = _underscore_tokens(report_text)
    for token in tokens:
        if token not in known:
            return (
                f"invented signal name found: '{token}' "
                f"(not in known signal rules: {sorted(known)})"
            )
    return None


def _load_quant_decisions(path: str) -> list[dict]:
    with open(path) as f:
        data = json.load(f)
    return data.get("decisions", [])


def check_quant_action_override(
    report_text: str, quant_decisions_path: str
) -> str | None:
    """Return an error if a SELL/REDUCE ticker lacks the required action words in the report."""
    REDUCE_SELL_KEYWORDS = ("一部売却", "売却")
    decisions = _load_quant_decisions(quant_decisions_path)
    for dec in decisions:
        action = dec.get("action", "")
        if action not in ("SELL", "REDUCE"):
            continue
        ticker = dec.get("ticker", "")
        if not ticker:
            continue

        # Scan each line that mentions this ticker + up to 4 following lines
        found = False
        lines = report_text.splitlines()
        for i, line in enumerate(lines):
            if ticker not in line:
                continue
            context = "\n".join(lines[i : i + 5])
            if any(kw in context for kw in REDUCE_SELL_KEYWORDS):
                found = True
                break

        if not found:
            return (
                f"quant action '{action}' for {ticker} requires action words "
                f"{REDUCE_SELL_KEYWORDS} in the report section, but none found"
            )
    return None


def check_account_label(report_text: str) -> str | None:
    """Return an error if the report uses the wrong account label."""
    if "信用倍率" in report_text:
        return "report contains '信用倍率'; expected '委託保証金率'"
    return None


def check_walk_forward_verdicts(
    report_text: str, backtest_dir: str
) -> str | None:
    """If 'robust' appears in the report, ensure every ticker has a 'robust' WF verdict."""
    if "robust" not in report_text:
        return None
    if not os.path.isdir(backtest_dir):
        return None

    non_robust: list[str] = []
    for fname in sorted(os.listdir(backtest_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(backtest_dir, fname)
        with open(fpath) as f:
            data = json.load(f)
        verdict = (
            data.get("walk_forward", {}).get("consensus", {}).get("verdict", "")
        )
        if verdict != "robust":
            ticker = fname.removesuffix(".json")
            non_robust.append(f"{ticker}: verdict='{verdict}'")

    if non_robust:
        return (
            "report claims 'robust' walk-forward but some tickers have "
            f"non-robust verdicts: {', '.join(non_robust)}"
        )
    return None


def check_position_count(report_text: str, portfolio_path: str | None) -> str | None:
    if not portfolio_path:
        return None
    with open(portfolio_path) as f:
        portfolio = yaml.safe_load(f) or {}
    expected = len(portfolio.get("holdings", []))
    # Count position headings: "#### 5803.T フジクラ（現物） — 一部売却（+3.7%）" or "### 285A.T ..."
    actual = len(re.findall(r"^(#### .+|### .+ — .+（[-+0-9.]+%）)$", report_text, re.MULTILINE))
    if actual != expected:
        return f"position count mismatch: portfolio={expected}, report={actual}"
    return None


def validate(
    report_path: str,
    signals_path: str,
    quant_decisions_path: str,
    backtest_dir: str,
    portfolio_path: str | None = None,
) -> list[str]:
    """Run all checks. Returns a list of error messages (empty = clean)."""
    with open(report_path) as f:
        report_text = f.read()

    errors: list[str] = []

    err = check_invented_signals(report_text, signals_path, quant_decisions_path, backtest_dir)
    if err:
        errors.append(err)

    err = check_quant_action_override(report_text, quant_decisions_path)
    if err:
        errors.append(err)

    err = check_account_label(report_text)
    if err:
        errors.append(err)

    err = check_walk_forward_verdicts(report_text, backtest_dir)
    if err:
        errors.append(err)

    err = check_position_count(report_text, portfolio_path)
    if err:
        errors.append(err)

    err = _check_strategy_gate_table(report_text)
    if err:
        errors.append(err)

    err = _check_forbidden_strategy_wording(report_text)
    if err:
        errors.append(err)

    err = _check_strategy_summary_consistency(report_text)
    if err:
        errors.append(err)

    return errors


def _check_strategy_summary_consistency(report_text: str) -> str | None:
    has_all_underperform_claim = "全銘柄でテクニカル戦略が B&H に劣後" in report_text
    has_candidate = "候補戦略（縮小執行）: 1銘柄" in report_text or "候補: " in report_text
    if has_all_underperform_claim and has_candidate:
        return "Report claims all strategies underperform while candidate strategies exist"
    return None


def _check_forbidden_strategy_wording(report_text: str) -> str | None:
    forbidden = ["手動レンジ", "手動判断", "裁量で売買"]
    for token in forbidden:
        if token in report_text:
            return f"Forbidden discretionary wording found: {token}"
    return None


def _check_strategy_gate_table(report_text: str) -> str | None:
    lines = report_text.splitlines()
    for idx, line in enumerate(lines):
        if line.strip() == "## Strategy Gate":
            table_lines = [l for l in lines[idx + 1: idx + 12] if l.startswith("|")]
            if len(table_lines) >= 2:
                expected = table_lines[0].count("|")
                for table_line in table_lines[1:]:
                    if table_line.count("|") != expected:
                        return (
                            f"Strategy Gate table column mismatch: "
                            f"expected {expected} pipes, got {table_line.count('|')}"
                        )
            break
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a generated stock report against known artifacts."
    )
    parser.add_argument(
        "--report", required=True, help="Path to the generated report file"
    )
    parser.add_argument(
        "--signals", required=True, help="Path to signals.json"
    )
    parser.add_argument(
        "--quant-decisions", required=True, help="Path to quant_decisions.json"
    )
    parser.add_argument(
        "--backtest-dir", required=True, help="Path to backtest directory"
    )
    parser.add_argument(
        "--portfolio", help="Optional portfolio.yaml path for position-count validation"
    )
    args = parser.parse_args()

    errors = validate(
        args.report, args.signals, args.quant_decisions, args.backtest_dir, args.portfolio
    )
    if errors:
        print("Validation FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
