import json
import os
import subprocess

import pytest


SCRIPT = os.path.join(os.path.dirname(__file__), "..", "fetch_stock_ir")

# Verified 2026-06-21 against real pages.
# - aktsk.jp: E-IR JS system, no static entries → unsupported.
# - kioxia-holdings.com: static HTML with discoverable links → success/partial.
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
def test_live_sync(ticker, tmp_path):
    _write_source(tmp_path, ticker)

    first = subprocess.run(
        [SCRIPT, ticker, "--refresh", "--data-dir", str(tmp_path)],
        text=True, capture_output=True, check=False,
    )
    assert first.returncode == 0, f"exit={first.returncode} stderr={first.stderr[:500]}"
    initial = json.loads(first.stdout)
    assert initial["ticker"] == ticker

    if ticker == "3932":
        # JS-rendered (E-IR) → must be unsupported
        assert initial["status"] == "unsupported", \
            f"JS site must be unsupported, got {initial['status']}"
    else:
        # Static HTML → must have discovered entries
        assert initial["status"] in ("success", "partial"), \
            f"status={initial['status']} errors={initial.get('errors')}"
        assert initial["summary"]["discovered"] > 0, \
            "Static IR page must yield discovered entries"
        assert len(initial.get("documents", [])) > 0, \
            "At least one document must be saved"
        assert initial["sync"]["mode"] == "initial"

    # Verify stdout is JSON-only, no secrets
    stdout_str = first.stdout
    for marker in ("Cookie", "Authorization", "token=", "password", ".tmp"):
        assert marker not in stdout_str, f"secret marker '{marker}' in stdout"

    if ticker == "3932":
        return

    # Incremental sync for static site
    second = subprocess.run(
        [SCRIPT, ticker, "--data-dir", str(tmp_path)],
        text=True, capture_output=True, check=False,
    )
    assert second.returncode == 0, f"incremental exit={second.returncode}"
    incremental = json.loads(second.stdout)
    assert incremental["status"] in ("success", "partial", "unsupported")
    assert incremental["sync"]["mode"] in ("incremental", "initial")
