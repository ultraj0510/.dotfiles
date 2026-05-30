"""Tests for run_stock_advisor_pipeline.py helpers."""

import pathlib

from run_stock_advisor_pipeline import collect_tickers


def test_collect_tickers_combines_holdings_and_watchlist(tmp_path):
    portfolio = tmp_path / "portfolio.yaml"
    portfolio.write_text("holdings:\n  - ticker: 1515.T\n  - ticker: 285A.T\n  - ticker: 1515.T\n")
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("- ticker: 7203.T\n- ticker: 285A.T\n")
    assert collect_tickers(portfolio, watchlist) == ["1515.T", "285A.T", "7203.T"]


def test_pipeline_uses_current_subcommand_cli_contract(tmp_path, monkeypatch):
    import json, sys, pathlib
    import run_stock_advisor_pipeline as pipeline

    portfolio = tmp_path / "portfolio.yaml"
    portfolio.write_text("holdings:\n  - ticker: 285A.T\n    name: Kioxia\n    quantity: 100\n", encoding="utf-8")
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("- ticker: 1515.T\n  name: Nittetsu Mining\n", encoding="utf-8")
    results_dir = tmp_path / "results"

    commands = []
    def fake_run(cmd):
        commands.append([str(part) for part in cmd])
        if "run_signal_engine" in cmd[0]:
            output = cmd[cmd.index("--output") + 1]
            pathlib.Path(output).write_text(json.dumps({"reference_date": "2026-05-30"}), encoding="utf-8")

    monkeypatch.setattr(pipeline, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["run_stock_advisor_pipeline.py", "--portfolio", str(portfolio), "--watchlist", str(watchlist), "--results-dir", str(results_dir)])
    pipeline.main()

    analytics_cmd = next(cmd for cmd in commands if cmd[1].endswith("portfolio_analytics.py"))
    assert "--portfolio" in analytics_cmd
    assert str(portfolio) in analytics_cmd
    assert "--signals" not in analytics_cmd

    decisions_cmd = next(cmd for cmd in commands if cmd[1].endswith("quant_decision_engine.py"))
    assert "--backtest-dir" in decisions_cmd
    assert str(results_dir / "backtest") in decisions_cmd
    assert "--portfolio-analytics" in decisions_cmd
    assert "--analytics" not in decisions_cmd


def test_collect_tickers_works_without_watchlist(tmp_path):
    portfolio = tmp_path / "portfolio.yaml"
    portfolio.write_text("holdings:\n  - ticker: 5803.T\n")
    watchlist = tmp_path / "missing.yaml"
    assert collect_tickers(portfolio, watchlist) == ["5803.T"]
