"""Smoke test requiring real SBI authentication. Opt-in via RUN_SBI_SMOKE=1."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from contract_assertions import assert_stock_info_contract, SENSITIVE_PARAMS

SCRIPT = Path(__file__).resolve().parents[1] / "fetch_stock_info"

SMOKE_TICKERS = ["3932", "285A"]


def _run_smoke(ticker, cache_dir):
    """Fresh fetch, cache validation, and cache-hit verification for one ticker."""
    run1 = subprocess.run(
        [str(SCRIPT), ticker, "--refresh", "--cache-dir", cache_dir],
        text=True, capture_output=True, check=False,
    )
    assert run1.returncode == 0, f"stderr: {run1.stderr}"
    result1 = json.loads(run1.stdout)
    assert_stock_info_contract(result1, require_useful=True, require_stock_reports=True)

    cache_file = Path(cache_dir) / f"{ticker}.json"
    assert cache_file.exists(), f"cache file not created for {ticker}"
    cache_payload = json.loads(cache_file.read_text())
    assert_stock_info_contract(cache_payload, require_useful=True, require_stock_reports=True)
    cache_str = json.dumps(cache_payload, ensure_ascii=False)
    for param in SENSITIVE_PARAMS:
        assert f"{param}=" not in cache_str.lower(), f"secret {param} in cache file"

    run2 = subprocess.run(
        [str(SCRIPT), ticker, "--cache-dir", cache_dir],
        text=True, capture_output=True, check=False,
    )
    assert run2.returncode == 0, f"stderr: {run2.stderr}"
    result2 = json.loads(run2.stdout)
    assert result2["cache"]["hit"] is True, "second run must hit cache"
    assert result2["ticker"] == result1["ticker"]
    assert result2["sections"] == result1["sections"]

    for run in (run1, run2):
        combined = run.stdout + run.stderr
        for param in SENSITIVE_PARAMS:
            assert f"{param}=" not in combined.lower(), f"secret {param} leaked"

    return result1


@pytest.mark.skipif(
    os.environ.get("RUN_SBI_SMOKE") != "1",
    reason="set RUN_SBI_SMOKE=1 for authenticated SBI smoke test",
)
@pytest.mark.parametrize("ticker", SMOKE_TICKERS)
def test_authenticated_smoke_useful_data_and_cache(ticker):
    with tempfile.TemporaryDirectory() as cache_dir:
        _run_smoke(ticker, cache_dir)
