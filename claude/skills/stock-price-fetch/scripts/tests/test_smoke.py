import json
import os
import subprocess

import pytest


SCRIPT = os.path.join(os.path.dirname(__file__), "..", "fetch_stock_price")


@pytest.mark.skipif(
    os.environ.get("RUN_PRICE_SMOKE") != "1",
    reason="set RUN_PRICE_SMOKE=1 for Yahoo Finance smoke test",
)
@pytest.mark.parametrize("ticker", ["3932", "285A"])
def test_live_initial_and_incremental_sync(ticker, tmp_path):
    first = subprocess.run(
        [SCRIPT, ticker, "--refresh", "--data-dir", str(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert first.returncode == 0, first.stderr
    initial = json.loads(first.stdout)
    assert initial["ticker"] == ticker
    assert initial["status"] in {"success", "partial"}
    assert initial["summary"]["usable"] is True
    assert initial["summary"]["daily_rows"] >= 200
    assert initial["summary"]["daily_first_date"]
    assert initial["summary"]["daily_last_date"]
    assert initial["data"]["daily"][-1]["close"] > 0

    second = subprocess.run(
        [SCRIPT, ticker, "--data-dir", str(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert second.returncode == 0, second.stderr
    incremental = json.loads(second.stdout)
    assert incremental["sync"]["mode"] in {"incremental", "full_reconcile"}
    assert incremental["summary"]["daily_rows"] >= initial["summary"]["daily_rows"]
    assert len({
        row["date"] for row in incremental["data"]["daily"]
    }) == incremental["summary"]["daily_rows"]
