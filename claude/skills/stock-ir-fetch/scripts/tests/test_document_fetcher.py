import hashlib
import pytest

from document_fetcher import fetch_document, MEDIA_TYPES


PDF_BYTES = b"%PDF-1.7\n%% fake pdf body"
XLSX_BYTES = b"PK\x03\x04\x00\x00\x00\x00\x00\x00fake xlsx"
HTML_BYTES = b"<!doctype html><html><body><main>IR material</main></body></html>"
CSV_BYTES = "日付,売上\n2026-05,100\n".encode("utf-8")


class FakeHttpClient:
    def __init__(self, body, content_type, final_url=None, status="ok"):
        self._body = body
        self._content_type = content_type
        self._final_url = final_url
        self._status = status
        self.calls = []

    def fetch(self, url, allowed_domains, max_bytes):
        self.calls.append((url, allowed_domains, max_bytes))
        from safe_http import FetchResult
        return FetchResult(self._body, self._status, url, self._final_url or url,
                          self._content_type, len(self._body) if self._body else 0)


def test_fetch_pdf_validates_signature():
    http = FakeHttpClient(PDF_BYTES, "application/pdf")
    doc, err = fetch_document("https://example.co.jp/ir/results.pdf",
                              {"example.co.jp"}, set(), http)
    assert err is None
    assert doc["extension"] == "pdf"
    assert doc["sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()


def test_fetch_rejects_pdf_with_wrong_signature():
    http = FakeHttpClient(b"<html>not pdf</html>", "application/pdf")
    doc, err = fetch_document("https://example.co.jp/ir/results.pdf",
                              {"example.co.jp"}, set(), http)
    assert err["code"] == "document_signature_mismatch"


def test_fetch_rejects_login_page():
    http = FakeHttpClient(b"<html><title>Login</title><form><input type=password></form></html>",
                          "application/pdf")
    doc, err = fetch_document("https://example.co.jp/ir/results.pdf",
                              {"example.co.jp"}, set(), http)
    assert err is not None


def test_fetch_accepts_html():
    http = FakeHttpClient(HTML_BYTES, "text/html")
    doc, err = fetch_document("https://example.co.jp/ir/page.html",
                              {"example.co.jp"}, set(), http)
    assert err is None
    assert doc["extension"] == "html"


def test_fetch_rejects_unapproved_domain():
    http = FakeHttpClient(PDF_BYTES, "application/pdf")
    doc, err = fetch_document("https://other.com/ir/results.pdf",
                              {"example.co.jp"}, set(), http)
    assert err["code"] == "unexpected_host"


def test_fetch_allows_delivery_domain():
    http = FakeHttpClient(PDF_BYTES, "application/pdf")
    doc, err = fetch_document("https://cdn.example.com/ir/results.pdf",
                              {"example.co.jp"}, {"example.com"}, http)
    assert err is None


def test_fetch_cleans_sensitive_params():
    http = FakeHttpClient(PDF_BYTES, "application/pdf",
                          final_url="https://example.co.jp/ir/results.pdf?token=abc123&page=1")
    doc, err = fetch_document("https://example.co.jp/ir/results.pdf?token=abc123&page=1",
                              {"example.co.jp"}, set(), http)
    assert err is None
    assert "token=abc123" not in doc["final_url"]
    assert "page=1" in doc["final_url"]
