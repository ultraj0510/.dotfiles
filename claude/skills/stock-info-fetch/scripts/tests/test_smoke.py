"""Smoke test requiring real SBI authentication. Opt-in via RUN_SBI_SMOKE=1."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from contract_assertions import assert_stock_info_contract, SENSITIVE_PARAMS

SCRIPT = Path(__file__).resolve().parents[1] / "fetch_stock_info"


@pytest.mark.skipif(
    os.environ.get("RUN_SBI_SMOKE") != "1",
    reason="set RUN_SBI_SMOKE=1 for authenticated SBI smoke test",
)
def test_authenticated_smoke_useful_data_and_cache():
    with tempfile.TemporaryDirectory() as cache_dir:
        # First run: --refresh, no cache
        run1 = subprocess.run(
            [str(SCRIPT), "3932", "--refresh", "--cache-dir", cache_dir],
            text=True, capture_output=True, check=False,
        )
        assert run1.returncode == 0, f"stderr: {run1.stderr}"
        result1 = json.loads(run1.stdout)
        assert_stock_info_contract(result1, require_useful=True, require_stock_reports=True)

        # Second run: should hit cache
        run2 = subprocess.run(
            [str(SCRIPT), "3932", "--cache-dir", cache_dir],
            text=True, capture_output=True, check=False,
        )
        assert run2.returncode == 0, f"stderr: {run2.stderr}"
        result2 = json.loads(run2.stdout)
        assert result2["cache"]["hit"] is True, "second run must hit cache"
        assert result2["ticker"] == result1["ticker"]
        assert_stock_info_contract(result2, require_useful=True, require_stock_reports=True)
        assert result2["sections"] == result1["sections"]

        # No secrets in any output
        for run in (run1, run2):
            combined = run.stdout + run.stderr
            for param in SENSITIVE_PARAMS:
                assert f"{param}=" not in combined, f"secret {param} leaked"
