"""Tests for report_skeleton_builder.py"""
import os
import subprocess
import tempfile

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = os.path.join(SCRIPTS_DIR, ".venv", "bin", "python")
BUILDER = os.path.join(SCRIPTS_DIR, "report_skeleton_builder.py")
FIXTURE_DIR = os.path.join(SCRIPTS_DIR, "tests", "fixtures", "report_quality")


def test_skeleton_builder_outputs_required_sections():
    with tempfile.TemporaryDirectory() as tmpdir:
        ctx = os.path.join(tmpdir, "report_context.json")
        report = os.path.join(tmpdir, "report.md")
        subprocess.run([
            PYTHON, os.path.join(SCRIPTS_DIR, "report_context_builder.py"),
            "--portfolio", os.path.join(FIXTURE_DIR, "portfolio.yaml"),
            "--signals", os.path.join(FIXTURE_DIR, "signals.json"),
            "--backtest-dir", os.path.join(FIXTURE_DIR, "backtest"),
            "--portfolio-analytics", os.path.join(FIXTURE_DIR, "portfolio_analytics.json"),
            "--quant-decisions", os.path.join(FIXTURE_DIR, "quant_decisions.json"),
            "-o", ctx,
        ], check=True)
        subprocess.run([PYTHON, BUILDER, "--context", ctx, "-o", report], check=True)
        text = open(report).read()
    assert "## 株式分析" in text
    assert "## 取引指示一覧" in text
    assert "## 銘柄別詳細" in text
    assert "## 本日の優先アクション" in text
