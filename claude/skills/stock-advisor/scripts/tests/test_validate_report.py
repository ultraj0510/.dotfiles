"""Tests for validate_report.py using subprocess to call the CLI validator."""

import os
import subprocess
import tempfile

FIXTURE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests",
    "fixtures",
    "report_quality",
)
VENV_PYTHON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".venv",
    "bin",
    "python",
)
VALIDATOR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "validate_report.py",
)


def _run_validator(report_text: str) -> subprocess.CompletedProcess:
    """Write report_text to a temp file and run validate_report.py against fixtures."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(report_text)
        report_path = f.name

    try:
        result = subprocess.run(
            [
                VENV_PYTHON,
                VALIDATOR,
                "--report",
                report_path,
                "--signals",
                os.path.join(FIXTURE_DIR, "signals.json"),
                "--quant-decisions",
                os.path.join(FIXTURE_DIR, "quant_decisions.json"),
                "--backtest-dir",
                os.path.join(FIXTURE_DIR, "backtest"),
            ],
            capture_output=True,
            text=True,
        )
    finally:
        os.unlink(report_path)

    return result


def test_rejects_invented_signal_name():
    """Report contains 'momentum_rising_80' which is not a known signal rule -> exit 1."""
    report = "285A.T: momentum_rising_80 signal detected\n5803.T: trend_following active\n"
    result = _run_validator(report)
    assert result.returncode == 1, f"expected exit 1, got {result.returncode}"
    assert "invented signal name" in result.stderr
    assert "momentum_rising_80" in result.stderr


def test_rejects_quant_action_override():
    """Report says '285A.T 保有継続' but quant_decisions says REDUCE -> exit 1."""
    report = "285A.T 保有継続\n5803.T also holding\n"
    result = _run_validator(report)
    assert result.returncode == 1, f"expected exit 1, got {result.returncode}"
    assert "quant action" in result.stderr
    assert "REDUCE" in result.stderr
    assert "285A.T" in result.stderr


def test_rejects_wrong_account_label():
    """Report says '信用倍率1,124倍' instead of '委託保証金率' -> exit 1."""
    report = "信用倍率1,124倍\n"
    result = _run_validator(report)
    assert result.returncode == 1, f"expected exit 1, got {result.returncode}"
    assert "信用倍率" in result.stderr


def test_accepts_artifact_aligned_snippet():
    """Report uses correct signal names + REDUCE action + 委託保証金率 + no robust claim -> exit 0."""
    report = """\
285A.T: trend_following signal detected, momentum active
285A.T 一部売却推奨
委託保証金率 30%
5803.T: drawdown_stop signal, 売却検討
"""
    result = _run_validator(report)
    assert result.returncode == 0, f"expected exit 0, stderr: {result.stderr}"


def test_accepts_known_metadata_tokens():
    """Metadata tokens in report should not be flagged as invented signals -> exit 0."""
    report = """\
285A.T 一部売却
5803.T 一部売却
open_date expiry_date quant_decisions risk_posture advisory_plan
委託保証金率 1124.46%
"""
    result = _run_validator(report)
    assert result.returncode == 0, result.stderr


def test_rejects_wrong_position_count(tmp_path):
    """Report has 1 position but portfolio has 2 holdings -> exit 1."""
    import subprocess as sp
    portfolio = tmp_path / "portfolio.yaml"
    portfolio.write_text("holdings:\n  - ticker: 285A.T\n  - ticker: 5803.T\n")
    report = tmp_path / "report.md"
    report.write_text("### 285A.T キオクシアHD — HOLD（+335.1%）\n")
    result = sp.run(
        [VENV_PYTHON, VALIDATOR,
         "--report", str(report),
         "--signals", os.path.join(FIXTURE_DIR, "signals.json"),
         "--quant-decisions", os.path.join(FIXTURE_DIR, "quant_decisions.json"),
         "--backtest-dir", os.path.join(FIXTURE_DIR, "backtest"),
         "--portfolio", str(portfolio)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "position count mismatch" in result.stderr
