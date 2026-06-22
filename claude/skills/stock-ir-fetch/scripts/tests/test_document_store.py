import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from document_store import DocumentStore, document_id, normalize_document_url

JST = ZoneInfo("Asia/Tokyo")
NOW = datetime(2026, 6, 21, 12, 0, tzinfo=JST)

PDF_BODY = b"%PDF-1.7\nfake pdf"
SHA = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
ENTRY = {"url": "https://example.co.jp/ir/results.pdf", "published_at": "2026-05-10", "title": "決算短信"}
FETCHED = {"body": PDF_BODY, "sha256": SHA, "extension": "pdf", "media_type": "application/pdf", "final_url": "https://example.co.jp/ir/results.pdf", "size": len(PDF_BODY)}
EXTRACTION = {"method": "pdf_text", "text": "決算短信テキスト", "page_count": 1, "quality_warnings": [], "error": None}


def test_document_id_ignores_tracking_params():
    a = document_id("https://example.co.jp/ir/results.pdf?utm_source=twitter&page=2", "2026-05-10")
    b = document_id("https://example.co.jp/ir/results.pdf?page=2", "2026-05-10")
    assert a == b


def test_normalize_document_url_removes_utm():
    url = "https://example.co.jp/ir/results.pdf?utm_source=twitter&page=2&ref=top"
    cleaned = normalize_document_url(url)
    assert "utm_source" not in cleaned
    assert "page=2" in cleaned


def test_save_version_creates_immutable_files(tmp_path):
    store = DocumentStore(tmp_path)
    result, is_new = store.save_version("285A", ENTRY, FETCHED, EXTRACTION, NOW)
    assert is_new
    assert result["sha256"] == SHA
    doc_id = result["document_id"]

    # Verify files exist
    doc_dir = tmp_path / "285A" / "raw" / "stock-ir-fetch" / "documents" / doc_id
    version_dir = doc_dir / "versions" / SHA
    assert (version_dir / "original.pdf").exists()
    assert (version_dir / "extracted.txt").exists()
    assert (version_dir / "extraction.json").exists()
    assert (doc_dir / "metadata.json").exists()

    # Second save with same SHA is not new
    result2, is_new2 = store.save_version("285A", ENTRY, FETCHED, EXTRACTION, NOW)
    assert not is_new2


def test_save_version_changed_hash_adds_new_version(tmp_path):
    store = DocumentStore(tmp_path)
    store.save_version("285A", ENTRY, FETCHED, EXTRACTION, NOW)

    sha2 = "a" * 64
    fetched2 = {**FETCHED, "sha256": sha2, "body": b"%PDF-1.7\nupdated pdf"}
    result, is_new = store.save_version("285A", ENTRY, fetched2, EXTRACTION, NOW)
    assert is_new

    doc_id = document_id(ENTRY["url"], ENTRY["published_at"])
    doc_dir = tmp_path / "285A" / "raw" / "stock-ir-fetch" / "documents" / doc_id
    meta = json.loads((doc_dir / "metadata.json").read_text())
    assert meta["version_count"] == 2


def _valid_manifest_1_1():
    return {
        "schema_version": "1.1",
        "run_id": "20260621T120000+0900-285A",
        "ticker": "285A",
        "as_of": NOW.isoformat(),
        "status": "partial",
        "sync": {
            "mode": "initial",
            "window_start": "2023-06-21",
            "window_end": "2026-06-21",
            "index_url": "https://example.co.jp/ir/library.html",
            "start_urls": [
                "https://example.co.jp/ir.html",
                "https://example.co.jp/ir/library.html",
            ],
            "visited_pages": ["https://example.co.jp/ir.html"],
            "dynamic_pages": ["https://example.co.jp/ir/data.html"],
            "index_parse_status": "incomplete",
        },
        "documents": [],
        "errors": [],
        "summary": {
            "discovered": 0,
            "new_documents": 0,
            "new_versions": 0,
            "unchanged": 0,
            "no_longer_listed": 0,
            "fetch_errors": 0,
            "extraction_errors": 0,
            "prohibited_documents": 0,
            "dynamic_pages": 1,
            "coverage_complete": False,
            "latest_published_at": None,
            "usable": False,
        },
    }


def test_save_manifest(tmp_path):
    store = DocumentStore(tmp_path)
    manifest = _valid_manifest_1_1()
    path = store.save_manifest("285A", manifest)
    loaded = store.load_manifest("285A")
    assert loaded is not None
    assert loaded["ticker"] == "285A"
    assert loaded["schema_version"] == "1.1"


def test_load_rejects_schema_1_0(tmp_path):
    store = DocumentStore(tmp_path)
    manifest = _valid_manifest_1_1()
    manifest["schema_version"] = "1.0"
    manifest["sync"].pop("start_urls", None)
    manifest["sync"].pop("dynamic_pages", None)
    manifest_path = store.manifest_path("285A")
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest))
    assert store.load_manifest("285A") is None


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("summary", "prohibited_documents"), -1),
        (("summary", "dynamic_pages"), True),
        (("summary", "coverage_complete"), "yes"),
        (("summary", "latest_published_at"), "2026-13-40"),
        (("sync", "start_urls"), "https://example.co.jp/ir"),
        (("sync", "dynamic_pages"), [123]),
    ],
)
def test_load_rejects_invalid_coverage_contract(tmp_path, path, value):
    store = DocumentStore(tmp_path)
    payload = _valid_manifest_1_1()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    manifest_path = store.manifest_path("285A")
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(payload))
    assert store.load_manifest("285A") is None


def test_load_rejects_corrupt_manifest(tmp_path):
    store = DocumentStore(tmp_path)
    path = store.manifest_path("285A")
    path.parent.mkdir(parents=True)
    path.write_text("not json")
    assert store.load_manifest("285A") is None
