"""Acceptance tests for 285A (alphanumeric ticker).

These tests define the contract that both numeric (3932) and alphanumeric
(285A) tickers must satisfy. Initially xfail — they will pass after
Tasks 2-9 fix the underlying parsers.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from contract_assertions import (
    assert_stock_info_contract,
    EXPECTED_SECTIONS,
    VALID_STATUSES,
    SENSITIVE_PARAMS,
)

SCRIPT = Path(__file__).resolve().parents[1] / "fetch_stock_info"


def _run_fetch(ticker, refresh=True, cache_dir=None):
    args = [str(SCRIPT), ticker]
    if refresh:
        args.append("--refresh")
    if cache_dir:
        args.extend(["--cache-dir", cache_dir])
    return subprocess.run(args, text=True, capture_output=True, check=False)


@pytest.mark.skipif(
    os.environ.get("RUN_SBI_SMOKE") != "1",
    reason="set RUN_SBI_SMOKE=1 for authenticated acceptance test",
)
def test_285A_useful_all_sections():
    """Every section must be ok or explicitly not_available. No errors allowed."""
    result = _run_fetch("285A", refresh=True)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    payload = json.loads(result.stdout)

    assert_stock_info_contract(payload, expected_ticker="285A")

    # All sections must be ok or explicitly not_available — no errors
    for name, section in payload["sections"].items():
        assert section["status"] in ("ok", "not_available"), (
            f"{name} status={section['status']}, errors: "
            f"{[e for e in payload.get('errors', []) if e['section'] == name]}"
        )

    # Price must have useful data
    price = payload["sections"]["price"]
    assert price["status"] == "ok"
    assert price["data"].get("current_price", 0) > 0

    # Company profile must have name
    profile = payload["sections"]["company_profile"]
    assert profile["status"] == "ok"
    assert profile["data"].get("company_name")

    # Company scores must have all 6 dimensions
    scores = payload["sections"]["company_scores"]
    assert scores["status"] == "ok"
    score_data = scores["data"]
    for key in ("total_score", "financial_health", "profitability",
                 "valuation", "stability", "price_momentum"):
        assert key in score_data, f"missing score dimension: {key}"

    # Performance must have at least one useful row
    perf = payload["sections"]["performance"]
    assert perf["status"] == "ok"

    # News must have items or explicit no-data
    news = payload["sections"]["news"]
    assert news["status"] in ("ok", "not_available")

    # Disclosures must have items or explicit no-data
    disc = payload["sections"]["disclosures"]
    assert disc["status"] in ("ok", "not_available")

    # STOCK REPORTS must have useful facts
    sr = payload["sections"]["stock_reports"]
    assert sr["status"] == "ok", f"stock_reports status={sr['status']}"
    sr_data = sr["data"]
    assert sr_data.get("report_date")
    has_metric = any(
        isinstance(v, dict) and v.get("value") is not None and v.get("unit")
        for v in sr_data.get("key_metrics", {}).values()
    )
    has_perf = any(
        item.get("value") is not None and item.get("period") and item.get("unit")
        for key in ("actual", "forecast")
        for item in sr_data.get("actual_and_forecast", {}).get(key, [])
    )
    assert has_metric or has_perf, "stock_reports has no useful facts"

    # No secrets in output
    combined = result.stdout + result.stderr
    for param in SENSITIVE_PARAMS:
        assert f"{param}=" not in combined.lower(), f"secret {param} leaked"


@pytest.mark.skipif(
    os.environ.get("RUN_SBI_SMOKE") != "1",
    reason="set RUN_SBI_SMOKE=1 for authenticated acceptance test",
)
def test_285A_cache_hit_preserves_contract():
    """Second run must be a verified cache hit with same sections."""
    with tempfile.TemporaryDirectory() as cache_dir:
        run1 = _run_fetch("285A", refresh=True, cache_dir=cache_dir)
        assert run1.returncode == 0
        result1 = json.loads(run1.stdout)

        run2 = _run_fetch("285A", refresh=False, cache_dir=cache_dir)
        assert run2.returncode == 0
        result2 = json.loads(run2.stdout)

        assert result2["cache"]["hit"] is True, "second run must hit cache"
        assert result2["ticker"] == "285A"
        assert result2["sections"] == result1["sections"]

        # Cache file must be valid and secret-free
        cache_file = Path(cache_dir) / "285A.json"
        assert cache_file.exists()
        cache_payload = json.loads(cache_file.read_text())
        assert_stock_info_contract(cache_payload, expected_ticker="285A")
        cache_str = json.dumps(cache_payload, ensure_ascii=False)
        for param in SENSITIVE_PARAMS:
            assert f"{param}=" not in cache_str.lower()
