import json
import os
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest


JST = ZoneInfo("Asia/Tokyo")
SCRIPT = os.path.join(os.path.dirname(__file__), "..", "fetch_stock_price")


@pytest.mark.skipif(
    os.environ.get("RUN_PRICE_SMOKE") != "1",
    reason="set RUN_PRICE_SMOKE=1 for Yahoo Finance smoke test",
)
@pytest.mark.parametrize("ticker", ["3932", "285A"])
def test_live_initial_and_incremental_sync(ticker, tmp_path):
    now = datetime.now(JST)

    # --- Initial sync ---
    first = subprocess.run(
        [SCRIPT, ticker, "--refresh", "--data-dir", str(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert first.returncode == 0, first.stderr
    initial = json.loads(first.stdout)
    assert initial["ticker"] == ticker
    # P2#4: require success, not partial
    assert initial["status"] == "success", f"status={initial['status']} errors={initial.get('errors')}"
    assert initial["summary"]["usable"] is True

    # Daily assertions
    daily = initial["data"]["daily"]
    assert daily["status"] == "ok"
    assert daily["fetched_at"]
    assert daily["data_as_of"]
    assert initial["summary"]["daily_rows"] >= 200
    assert initial["summary"]["daily_first_date"]
    assert initial["summary"]["daily_last_date"]
    assert daily["bars"][-1]["close"] > 0

    # Daily period: verify coverage spans at least 1 year back (new listings may
    # have less than 5 years; ≥200 rows already verified above)
    first_date = datetime.fromisoformat(initial["summary"]["daily_first_date"]).replace(tzinfo=JST)
    one_year_ago = now.replace(year=now.year - 1)
    assert first_date <= one_year_ago, f"daily_first_date {first_date.date()} not before 1y ago {one_year_ago.date()}"

    # Intraday assertions (P2#4: must have bars)
    intraday = initial["data"]["intraday_1h"]
    assert intraday["status"] == "ok"
    assert initial["summary"]["intraday_rows"] > 0, "intraday must have bars"
    assert intraday["fetched_at"]
    assert intraday["data_as_of"]
    assert initial["summary"]["intraday_first_timestamp"]
    assert initial["summary"]["intraday_last_timestamp"]

    # No duplicate dates/timestamps
    assert len({row["date"] for row in daily["bars"]}) == len(daily["bars"])
    assert len({row["timestamp"] for row in intraday["bars"]}) == len(intraday["bars"])

    # --- Incremental sync ---
    second = subprocess.run(
        [SCRIPT, ticker, "--data-dir", str(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert second.returncode == 0, second.stderr
    incremental = json.loads(second.stdout)
    assert incremental["status"] == "success", f"incremental status={incremental['status']}"
    assert incremental["sync"]["mode"] in {"incremental", "full_reconcile"}
    assert incremental["summary"]["daily_rows"] >= initial["summary"]["daily_rows"]
    assert incremental["summary"]["intraday_rows"] >= 0

    inc_daily = incremental["data"]["daily"]
    assert len({row["date"] for row in inc_daily["bars"]}) == len(inc_daily["bars"])
