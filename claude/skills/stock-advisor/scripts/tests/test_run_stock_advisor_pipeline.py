"""Tests for run_stock_advisor_pipeline.py helpers."""

import json
import pathlib
import sys

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


def test_pipeline_includes_wf_research_in_backtest_commands(tmp_path, monkeypatch):
    import run_stock_advisor_pipeline as pipeline

    portfolio = tmp_path / "portfolio.yaml"
    portfolio.write_text("holdings:\n  - ticker: 285A.T\n    name: Kioxia\n    quantity: 100\n", encoding="utf-8")
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("", encoding="utf-8")
    results_dir = tmp_path / "results"

    commands = []
    def fake_run(cmd):
        command = [str(part) for part in cmd]
        commands.append(command)
        if "run_signal_engine" in command[0]:
            output = command[command.index("--output") + 1]
            pathlib.Path(output).write_text(json.dumps({"reference_date": "2026-05-30"}), encoding="utf-8")
        elif command[1].endswith("report_context_builder.py"):
            output = command[command.index("-o") + 1]
            pathlib.Path(output).write_text(json.dumps({"price_freshness": {"stale_count": 0}}), encoding="utf-8")

    monkeypatch.setattr(pipeline, "run", fake_run)
    monkeypatch.setattr(sys, "argv", [
        "run_stock_advisor_pipeline.py", "--portfolio", str(portfolio),
        "--watchlist", str(watchlist), "--results-dir", str(results_dir),
    ])
    pipeline.main()

    backtest_cmds = [c for c in commands if c[1].endswith("backtest_engine.py")]
    assert backtest_cmds
    for cmd in backtest_cmds:
        assert "--wf-research" in cmd, f"Missing --wf-research in {cmd}"
        assert "--no-cache" in cmd, f"Missing --no-cache in {cmd}"

    manifest = json.loads((results_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["settings"]["wf_research"] is True


def test_pipeline_skip_wf_research_excludes_flags(tmp_path, monkeypatch):
    import run_stock_advisor_pipeline as pipeline

    portfolio = tmp_path / "portfolio.yaml"
    portfolio.write_text("holdings:\n  - ticker: 285A.T\n", encoding="utf-8")
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("", encoding="utf-8")
    results_dir = tmp_path / "results"

    commands = []
    def fake_run(cmd):
        command = [str(part) for part in cmd]
        commands.append(command)
        if "run_signal_engine" in command[0]:
            output = command[command.index("--output") + 1]
            pathlib.Path(output).write_text(json.dumps({"reference_date": "2026-05-30"}), encoding="utf-8")
        elif command[1].endswith("report_context_builder.py"):
            output = command[command.index("-o") + 1]
            pathlib.Path(output).write_text(json.dumps({"price_freshness": {"stale_count": 0}}), encoding="utf-8")

    monkeypatch.setattr(pipeline, "run", fake_run)
    monkeypatch.setattr(sys, "argv", [
        "run_stock_advisor_pipeline.py", "--portfolio", str(portfolio),
        "--watchlist", str(watchlist), "--results-dir", str(results_dir),
        "--skip-wf-research",
    ])
    pipeline.main()

    backtest_cmd = next(c for c in commands if c[1].endswith("backtest_engine.py"))
    assert "--wf-research" not in backtest_cmd
    assert "--no-cache" not in backtest_cmd

    manifest = json.loads((results_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["settings"]["wf_research"] is False
