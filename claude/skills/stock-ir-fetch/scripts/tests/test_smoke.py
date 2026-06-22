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
        "ir_top_url": "https://www.kioxia-holdings.com/ja-jp/ir.html",
        "document_index_url": "https://www.kioxia-holdings.com/ja-jp/ir/library.html",
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

    # 285A: static HTML IR site — expect partial sync with schema 1.1
    assert initial["schema_version"] == "1.1"
    assert initial["status"] == "partial"
    assert initial["sync"]["mode"] == "initial"
    # Window must cover ~3 years (±31 days for calendar edge cases)
    from datetime import date, datetime
    from zoneinfo import ZoneInfo
    JST = ZoneInfo("Asia/Tokyo")
    now = datetime.now(JST)
    win_start = date.fromisoformat(initial["sync"]["window_start"])
    expected_3y = now.replace(year=now.year - 3).date()
    assert abs((win_start - expected_3y).days) <= 31, f"window_start={win_start} expected~{expected_3y}"
    assert initial["summary"]["discovered"] > 0, "No entries discovered"
    docs = initial.get("documents", [])
    assert len(docs) > 0, "No documents saved"

    # Coverage must reflect incomplete static scan
    assert initial["summary"]["usable"] is True
    assert initial["summary"]["coverage_complete"] is False
    assert initial["summary"]["dynamic_pages"] > 0
    assert initial["summary"]["prohibited_documents"] > 0
    assert initial["summary"]["latest_published_at"] >= "2026-06-02"

    # Must contain 2026-06-02 Investor Day document
    assert any(
        d["published_at"] == "2026-06-02"
        and d["category"] == "other_relevant"
        and "プレゼンテーション資料" in d["title"]
        for d in initial["documents"]
    ), f"No 2026-06-02 Investor Day doc. Docs: {[(d['title'][:60], d['published_at'], d['category']) for d in docs]}"

    # At least one must have a standard IR category
    ir_cats = {"earnings_release", "earnings_presentation", "securities_report",
               "management_plan", "forecast_revision", "business_kpi", "material_disclosure"}
    doc_cats = {d.get("category") for d in docs}
    assert doc_cats & ir_cats, f"No IR category in {doc_cats}"

    # Verify no duplicates in document_ids
    doc_ids = [d["document_id"] for d in docs]
    assert len(doc_ids) == len(set(doc_ids)), f"Duplicate document_ids"

    # All document_ids must be 24-char hex
    for did in doc_ids:
        assert len(did) == 24 and all(c in "0123456789abcdef" for c in did), f"Bad doc_id: {did}"

    # All document URLs must be on approved domain or allowed delivery domain
    # (KIOXIA uses eir-parts.net for E-IR delivery — not TDnet/EDINET)
    import hashlib, os as _os
    base = tmp_path / "285A" / "raw" / "stock-ir-fetch" / "documents"
    _PROHIBITED_DELIVERY = ("tdnet", "edinet", "disclosure.edinet-fsa", "eoldisclosure")
    for d in docs:
        did = d["document_id"]
        meta_path = base / did / "metadata.json"
        assert meta_path.exists(), f"metadata.json missing for {did}"
        meta = json.loads(meta_path.read_text())
        doc_url = meta.get("url", "")
        url_lower = doc_url.lower()
        assert not any(kw in url_lower for kw in _PROHIBITED_DELIVERY), \
            f"Document {did} hosted on prohibited domain: {doc_url}"
    # Investor Day documents must be on kioxia-holdings.com
    investor_day_docs = [d for d in docs if d["published_at"] == "2026-06-02"]
    for d in investor_day_docs:
        meta = json.loads((base / d["document_id"] / "metadata.json").read_text())
        assert "kioxia-holdings.com" in meta.get("url", ""), \
            f"Investor Day doc not on company domain: {meta.get('url')}"

    # Verify SHA-256 and extracted text for each saved document
    mtimes_before = {}
    for d in docs:
        did = d["document_id"]
        sha_manifest = d["sha256"]
        doc_dir = base / did
        meta_path = doc_dir / "metadata.json"
        meta = json.loads(meta_path.read_text())
        latest_sha = meta.get("latest_sha256", "")
        assert latest_sha == sha_manifest, \
            f"metadata SHA != manifest SHA: {latest_sha[:12]} vs {sha_manifest[:12]}"
        ver_dir = doc_dir / "versions" / latest_sha
        orig_files = list(ver_dir.glob("original.*"))
        assert orig_files, f"No original.* in {ver_dir}"
        orig_path = orig_files[0]
        actual_sha = hashlib.sha256(orig_path.read_bytes()).hexdigest()
        assert actual_sha == sha_manifest, \
            f"original SHA != manifest SHA: {actual_sha[:12]} vs {sha_manifest[:12]}"
        txt_path = ver_dir / "extracted.txt"
        assert txt_path.exists(), f"extracted.txt missing for {did}"
        txt = txt_path.read_text()
        assert len(txt.strip()) > 0, f"extracted.txt empty for {did}"
        mtimes_before[did] = _os.stat(str(orig_path)).st_ino

    # No TDnet/EDINET references anywhere
    for kw in ("tdnet", "edinet"):
        assert kw not in first.stdout.lower(), f"TDnet/EDINET in stdout"
        for e in initial.get("errors", []):
            assert kw not in str(e).lower(), f"TDnet/EDINET in errors"

    for marker in ("Cookie", "Authorization", "token=", "password", ".tmp"):
        assert marker not in first.stdout

    # Incremental sync
    second = subprocess.run(
        [SCRIPT, ticker, "--data-dir", str(tmp_path)],
        text=True, capture_output=True, check=False,
    )
    assert second.returncode == 0
    incremental = json.loads(second.stdout)
    assert incremental["schema_version"] == "1.1"
    assert incremental["status"] == "partial"
    assert incremental["sync"]["mode"] == "incremental", \
        f"Expected incremental, got {incremental['sync']['mode']}"
    inc_start = date.fromisoformat(incremental["sync"]["window_start"])
    expected_90d = (now - __import__("datetime").timedelta(days=90)).date()
    assert abs((inc_start - expected_90d).days) <= 3, f"inc window_start={inc_start} expected~{expected_90d}"
    assert incremental["summary"]["unchanged"] > 0, f"No unchanged docs in incremental sync"
    assert incremental["summary"]["usable"] is True
    assert incremental["summary"]["coverage_complete"] is False
    assert incremental["summary"]["latest_published_at"] == initial["summary"]["latest_published_at"]

    # Verify originals were NOT re-written (same inode)
    for d in incremental.get("documents", []):
        did = d["document_id"]
        assert did in mtimes_before, f"Doc {did} not in first-run set"
        sha = d["sha256"]
        ver_dir = base / did / "versions" / sha
        orig_files = list(ver_dir.glob("original.*"))
        assert orig_files, f"Original missing on second run for {did}"
        new_ino = _os.stat(str(orig_files[0])).st_ino
        assert new_ino == mtimes_before[did], f"Original re-written for {did}"

    # Prohibited delivery links must not be saved
    for kw in ("tdnet", "edinet"):
        assert kw not in second.stdout.lower()
        for e in incremental.get("errors", []):
            assert kw not in str(e).lower()

    for marker in ("Cookie", "Authorization", "token=", "password", ".tmp"):
        assert marker not in second.stdout
