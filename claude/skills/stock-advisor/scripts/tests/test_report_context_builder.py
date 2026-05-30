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
