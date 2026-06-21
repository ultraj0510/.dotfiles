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
        "document_index_url": "https://www.kioxia-holdings.com/ja-jp/ir/",
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
    initial = json.loads(first.stdout)
    assert initial["ticker"] == ticker

    if ticker == "3932":
        assert initial["status"] in ("unsupported", "failed"), \
            f"JS site must be unsupported/failed, got {initial['status']}"
        for marker in ("Cookie", "Authorization", "token=", "password", ".tmp"):
            assert marker not in first.stdout
        return

    # 285A: static HTML IR site — expect usable sync with documents
    assert initial["status"] in ("success", "partial"), \
        f"status={initial['status']} errors={initial.get('errors')}"
    assert initial["sync"]["mode"] == "initial"
    assert initial["summary"]["discovered"] > 0, "No entries discovered"
    docs = initial.get("documents", [])
    assert len(docs) > 0, "No documents saved"

    # At least one must have a standard IR category
    ir_cats = {"earnings_release", "earnings_presentation", "securities_report",
               "management_plan", "forecast_revision", "business_kpi", "material_disclosure"}
    doc_cats = {d.get("category") for d in docs}
    assert doc_cats & ir_cats, f"No IR category in {doc_cats}. docs: {[(d['title'][:60], d['category']) for d in docs[:5]]}"

    # If scan is complete, usable must be True
    if initial["sync"]["index_parse_status"] == "ok":
        assert initial["summary"]["usable"] is True

    # Verify no duplicates in document_ids
    doc_ids = [d["document_id"] for d in docs]
    assert len(doc_ids) == len(set(doc_ids)), f"Duplicate document_ids: {len(doc_ids)} vs {len(set(doc_ids))}"

    for marker in ("Cookie", "Authorization", "token=", "password", ".tmp"):
        assert marker not in first.stdout

    # Incremental sync: must be incremental mode, 90-day window
    second = subprocess.run(
        [SCRIPT, ticker, "--data-dir", str(tmp_path)],
        text=True, capture_output=True, check=False,
    )
    assert second.returncode == 0
    incremental = json.loads(second.stdout)
    assert incremental["status"] in ("success", "partial")
    assert incremental["sync"]["mode"] == "incremental", \
        f"Expected incremental, got {incremental['sync']['mode']}"
    assert incremental["summary"]["unchanged"] >= 0
