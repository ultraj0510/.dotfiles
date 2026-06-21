from datetime import datetime, date
from zoneinfo import ZoneInfo
from pathlib import Path

from fetch_stock_ir import fetch_stock_ir

JST = ZoneInfo("Asia/Tokyo")
NOW = datetime(2026, 6, 21, 12, 0, tzinfo=JST)

IR_HTML = ('<table><tr><td>2026-05-10</td>'
           '<td><a href="/ir/results.pdf">2026年3月期 決算短信</a></td></tr></table>').encode("utf-8")
IR_INDEX_HTML = '<a href="/ir/">IR</a>'.encode("utf-8")
PDF_BODY = b"%PDF-1.7\nfake pdf content here more text for extraction extra padding to reach minimum text length for pdf text extraction method"


class FakeHttp:
    def __init__(self, responses=None):
        self._responses = responses or {}
        self.calls = []

    def fetch(self, url, allowed_domains, max_bytes):
        self.calls.append(url)
        from safe_http import FetchResult
        resp = self._responses.get(url)
        if resp:
            return FetchResult(resp.get("body", b""), resp.get("status", "ok"),
                              url, url, resp.get("content_type", "text/html"),
                              len(resp.get("body", b"")))
        return FetchResult(None, "not_found", url, url, "", 0)


class FakeMetadataNoSite:
    def lookup(self, ticker):
        return {"company_name": "Test", "company_site_url": ""}


class FakeMetadata:
    def lookup(self, ticker):
        return {"company_name": "Test Inc.", "company_site_url": "https://example.co.jp/"}


class FakeRegistry:
    def __init__(self, source=None):
        self.source = source
        self.approved = None
        self.sync_updates = []

    def load(self, ticker):
        return self.source

    def approve(self, ticker, candidate, approved_at):
        src = {**candidate, "schema_version": "1.0", "ticker": ticker,
               "approved_at": approved_at.isoformat(), "last_verified_at": approved_at.isoformat(),
               "last_successful_sync_at": None, "approval_method": "user",
               "approved_domain": candidate.get("approved_domain", "example.co.jp")}
        self.source = src
        return src

    def update_sync_times(self, ticker, verified_at, successful_at):
        self.sync_updates.append((verified_at, successful_at))
        return self.source


class FakeStore:
    def __init__(self):
        self.manifests = {}
        self.versions = []

    def load_manifest(self, ticker):
        return self.manifests.get(ticker)

    def save_manifest(self, ticker, manifest):
        self.manifests[ticker] = manifest
        return Path("/fake")

    def save_version(self, ticker, entry, fetched, extraction, now):
        self.versions.append((entry["url"], fetched["sha256"]))
        from document_store import document_id
        return {"document_id": document_id(entry["url"], entry["published_at"]),
                "sha256": fetched["sha256"], "is_new_document": True}, True


def _deps():
    http = FakeHttp({
        "https://example.co.jp/": {"body": IR_INDEX_HTML, "content_type": "text/html", "status": "ok"},
        "https://example.co.jp/ir/": {"body": IR_HTML, "content_type": "text/html", "status": "ok"},
        "https://example.co.jp/ir/results.pdf": {"body": PDF_BODY, "content_type": "application/pdf", "status": "ok"},
    })
    registry = FakeRegistry({
        "schema_version": "1.0", "ticker": "285A",
        "company_name": "Test Inc.", "company_site_url": "https://example.co.jp/",
        "ir_top_url": "https://example.co.jp/ir/",
        "document_index_url": "https://example.co.jp/ir/",
        "approved_domain": "example.co.jp",
        "approved_at": NOW.isoformat(), "last_verified_at": NOW.isoformat(),
        "last_successful_sync_at": None, "approval_method": "user",
    })
    store = FakeStore()
    return {"http_client": http, "registry": registry, "store": store,
            "metadata_provider": FakeMetadata()}


def test_confirmation_required_when_no_source_and_no_candidates(tmp_path):
    http = FakeHttp()
    registry = FakeRegistry(None)
    deps = {"http_client": http, "registry": registry, "store": FakeStore(),
            "metadata_provider": FakeMetadataNoSite()}
    result = fetch_stock_ir("285A", tmp_path, now=NOW, dependencies=deps)
    assert result["status"] == "confirmation_required"


def test_invalid_ticker_returns_failed(tmp_path):
    result = fetch_stock_ir("bad;cmd", tmp_path, now=NOW)
    assert result["status"] == "failed"


def test_approved_source_runs_sync(tmp_path):
    deps = _deps()
    fake_store = deps["store"]
    result = fetch_stock_ir("285A", tmp_path, now=NOW, dependencies=deps)
    assert result["status"] in ("success", "partial"), f"status={result['status']} errors={result.get('errors')}"
    assert result["sync"]["mode"] == "initial"
    assert result["summary"]["discovered"] >= 1
    assert len(fake_store.versions) >= 1


def test_ticker_with_candidates_returns_confirmation_required(tmp_path):
    http = FakeHttp({
        "https://example.co.jp/": {"body": IR_INDEX_HTML, "content_type": "text/html", "status": "ok"},
        "https://example.co.jp/ir/": {"body": IR_HTML, "content_type": "text/html", "status": "ok"},
    })
    registry = FakeRegistry(None)
    deps = {"http_client": http, "registry": registry, "store": FakeStore(),
            "metadata_provider": FakeMetadata()}
    result = fetch_stock_ir("285A", tmp_path, now=NOW, dependencies=deps)
    assert result["status"] == "confirmation_required"
    assert "candidates" in result
