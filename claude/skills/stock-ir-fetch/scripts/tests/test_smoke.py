import json
import os
import subprocess

import pytest


SCRIPT = os.path.join(os.path.dirname(__file__), "..", "fetch_stock_ir")

SMOKE_SOURCES = {
    "3932": {
        "company_name": "Akatsuki Inc.",
        "company_site_url": "https://aktsk.jp/",
        "ir_top_url": "https://aktsk.jp/ir/",
        "document_index_url": "https://aktsk.jp/ir/",
        "approved_domain": "aktsk.jp",
    },
    "285A": {
        "company_name": "KIOXIA HOLDINGS CORPORATION",
        "company_site_url": "https://www.kioxia-holdings.com/",
        "ir_top_url": "https://www.kioxia-holdings.com/ja-jp/ir/",
        "document_index_url": "https://www.kioxia-holdings.com/ja-jp/ir/library/data.html",
        "approved_domain": "kioxia-holdings.com",
    },
}


def _write_source(tmp_path, ticker):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    JST = ZoneInfo("Asia/Tokyo")
    now = datetime.now(JST)
    source = SMOKE_SOURCES[ticker]
    source_path = tmp_path / ticker / "raw" / "stock-ir-fetch" / "source.json"
    source_path.parent.mkdir(parents=True)
    payload = {
        "schema_version": "1.0",
        "ticker": ticker,
        **source,
        "approved_at": now.isoformat(),
        "last_verified_at": now.isoformat(),
        "last_successful_sync_at": None,
        "approval_method": "user",
    }
    source_path.write_text(json.dumps(payload, ensure_ascii=False))
    return tmp_path


@pytest.mark.skipif(
    os.environ.get("RUN_IR_SMOKE") != "1",
    reason="set RUN_IR_SMOKE=1 for live IR smoke test",
)
@pytest.mark.parametrize("ticker", ["3932", "285A"])
def test_live_sync_detects_js_rendered_site(ticker, tmp_path):
    _write_source(tmp_path, ticker)

    first = subprocess.run(
        [SCRIPT, ticker, "--refresh", "--data-dir", str(tmp_path)],
        text=True, capture_output=True, check=False,
    )
    initial = json.loads(first.stdout)
    assert initial["ticker"] == ticker

    # JS-rendered sites: must return unsupported or failed (never success)
    assert initial["status"] in ("unsupported", "failed"), \
        f"JS site must be unsupported/failed, got {initial['status']}"

    # No secrets in stdout
    for marker in ("Cookie", "Authorization", "token=", "password", ".tmp"):
        assert marker not in first.stdout

    # Second run must not crash
    second = subprocess.run(
        [SCRIPT, ticker, "--data-dir", str(tmp_path)],
        text=True, capture_output=True, check=False,
    )
    incremental = json.loads(second.stdout)
    assert incremental["status"] in ("unsupported", "failed")
