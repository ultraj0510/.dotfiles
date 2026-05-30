"""Tests for report_context_builder.py via subprocess with fixture data."""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_DIR = os.path.join(SCRIPTS_DIR, "tests", "fixtures", "report_quality")
BACKTEST_DIR = os.path.join(FIXTURE_DIR, "backtest")
PYTHON = os.path.join(SCRIPTS_DIR, ".venv", "bin", "python")
BUILDER = os.path.join(SCRIPTS_DIR, "report_context_builder.py")


def _run_builder() -> dict:
    """Run report_context_builder.py with fixture paths and return parsed output."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        output_path = tmp.name
    try:
        result = subprocess.run(
            [
                PYTHON, BUILDER,
                "--portfolio", os.path.join(FIXTURE_DIR, "portfolio.yaml"),
                "--signals", os.path.join(FIXTURE_DIR, "signals.json"),
                "--backtest-dir", BACKTEST_DIR,
                "--portfolio-analytics", os.path.join(FIXTURE_DIR, "portfolio_analytics.json"),
                "--quant-decisions", os.path.join(FIXTURE_DIR, "quant_decisions.json"),
                "-o", output_path,
            ],
            capture_output=True, text=True, check=True,
        )
        with open(output_path) as f:
            return json.load(f)
    finally:
        os.unlink(output_path)


class TestReportContextBuilder:
    def test_preserves_signal_rule_names(self):
        """285A.T signals are [trend_following, momentum, overbought], 5803.T is [drawdown_stop]."""
        context = _run_builder()
        signals = context["signals"]

        assert "285A.T" in signals
        rules_285a = [s["rule"] for s in signals["285A.T"]["signals"]]
        assert rules_285a == ["trend_following", "momentum", "overbought"]

        assert "5803.T" in signals
        rules_5803 = [s["rule"] for s in signals["5803.T"]["signals"]]
        assert rules_5803 == ["drawdown_stop"]

    def test_preserves_quant_actions_as_report_actions(self):
        """285A.T report_action=REDUCE order_shares=100, 5803.T report_action=REDUCE order_shares=300."""
        context = _run_builder()
        decisions = context["quant_decisions"]["decisions"]

        assert "285A.T" in decisions
        assert decisions["285A.T"]["report_action"] == "REDUCE"
        assert decisions["285A.T"]["order_shares"] == 100

        assert "5803.T" in decisions
        assert decisions["5803.T"]["report_action"] == "REDUCE"
        assert decisions["5803.T"]["order_shares"] == 300

    def test_account_labels_are_report_ready(self):
        """margin_ratio_label is 委託保証金率, margin_ratio_text is 1124.46%."""
        context = _run_builder()
        account = context["account"]

        assert account["margin_ratio_label"] == "委託保証金率"
        assert account["margin_ratio_text"] == "1124.46%"

    def test_watchlist_is_separate_from_holdings(self):
        """watchlist has 8411.T, holdings doesn't."""
        context = _run_builder()

        watchlist_tickers = [w["ticker"] for w in context["watchlist"]]
        assert "8411.T" in watchlist_tickers

        holding_tickers = [h["ticker"] for h in context["holdings"]]
        assert "8411.T" not in holding_tickers

    def test_walk_forward_verdict_is_not_upgraded(self):
        """285A.T verdict=unstable, 5803.T verdict=insufficient_data."""
        context = _run_builder()
        backtest = context["backtest"]

        assert backtest["285A.T"]["walk_forward"]["verdict"] == "unstable"
        assert backtest["5803.T"]["walk_forward"]["verdict"] == "insufficient_data"


def test_quant_risk_posture_fields_are_exported():
    context = _run_builder()
    decisions = context.get("quant_decisions", {}).get("decisions", {})
    sample = decisions.get("285A.T", {})
    for key in [
        "risk_posture", "protective_stop_price", "portfolio_weight_pct",
        "cost_basis_weight_pct", "unrealized_pnl_pct",
        "downside_10pct_yen", "advisory_plan",
    ]:
        assert key in sample, f"missing key: {key}"


def test_build_quant_decisions_preserves_risk_flags():
    from report_context_builder import build_quant_decisions

    context = build_quant_decisions({
        "generated_at": "2026-05-30T00:00:00",
        "decisions": [
            {
                "ticker": "5803.T",
                "action": "REDUCE",
                "confidence": "moderate",
                "order_shares": 300,
                "order_type": "limit",
                "limit_price": 4771.0,
                "vetoes": [],
                "risk_flags": ["negative_walk_forward"],
                "explanations": ["limit sell 300sh across 2 positions"],
                "risk_posture": "neutral",
                "protective_stop_price": None,
                "portfolio_weight_pct": 7.28,
                "cost_basis_weight_pct": 7.39,
                "unrealized_pnl_pct": -1.43,
                "downside_10pct_yen": 143130,
                "advisory_plan": {},
            }
        ],
    })

    decision = context["decisions"]["5803.T"]
    assert decision["report_action"] == "REDUCE"
    assert decision["vetoes"] == []
    assert decision["risk_flags"] == ["negative_walk_forward"]


def test_context_fixture_preserves_any_risk_flags_when_present(tmp_path):
    from report_context_builder import build_quant_decisions

    decisions = {
        "generated_at": None,
        "decisions": [
            {
                "ticker": "1515.T",
                "action": "HOLD",
                "confidence": "moderate",
                "order_shares": 0,
                "order_type": "none",
                "limit_price": None,
                "vetoes": [],
                "risk_flags": ["negative_walk_forward", "position_over_cap_loss_concentration"],
                "explanations": ["no actionable signal"],
                "risk_posture": "rebalance_on_strength",
                "protective_stop_price": None,
                "portfolio_weight_pct": 36.57,
                "cost_basis_weight_pct": 54.2,
                "unrealized_pnl_pct": -32.52,
                "downside_10pct_yen": 719100,
                "advisory_plan": {
                    "mode": "trim_on_rebound_rebuy_on_pullback",
                    "trim_shares": 300,
                    "trim_trigger_price": 2440.4,
                    "reentry_watch_price": 2162.25,
                    "max_reentry_shares": 300,
                    "reentry_allowed_after_trim": True,
                    "reentry_requires": [
                        "trim_filled",
                        "price_near_lower_band",
                        "rsi_below_40_or_reversal_signal",
                    ],
                },
            }
        ],
    }

    context = build_quant_decisions(decisions)

    assert context["decisions"]["1515.T"]["risk_flags"] == [
        "negative_walk_forward",
        "position_over_cap_loss_concentration",
    ]
