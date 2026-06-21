import pytest

from source_discovery import (
    candidate_id,
    discover_candidates,
    discover_ir_links,
    validate_user_source,
    YahooCompanyMetadataProvider,
)


# --- candidate_id ---

def test_candidate_id_is_stable():
    first = candidate_id("https://example.co.jp/", "https://example.co.jp/ir/", "https://example.co.jp/ir/library/")
    second = candidate_id("https://example.co.jp", "https://example.co.jp/ir/#top", "https://example.co.jp/ir/library/")
    assert first == second


def test_candidate_id_differs_on_change():
    a = candidate_id("https://a.co.jp/", "https://a.co.jp/ir/", "https://a.co.jp/ir/library/")
    b = candidate_id("https://b.co.jp/", "https://a.co.jp/ir/", "https://a.co.jp/ir/library/")
    assert a != b


# --- discover_ir_links ---

def test_discovers_ir_top_and_library_links():
    company_html = '<a href="/ir/">株主・投資家情報</a>'
    ir_html = '<a href="/ir/library/">IRライブラリー</a>'
    result = discover_ir_links(
        "https://example.co.jp/",
        company_html,
        "https://example.co.jp/ir/",
        ir_html,
    )
    assert result["ir_top_url"] == "https://example.co.jp/ir/"
    assert result["document_index_url"] == "https://example.co.jp/ir/library/"


def test_does_not_treat_external_directory_as_official():
    result = discover_ir_links(
        "https://example.co.jp/",
        '<a href="https://finance.example.net/example">IR</a>',
        "",
        "",
    )
    assert result is None


def test_discovers_investor_label():
    company_html = '<a href="/en/investor/">Investor Relations</a>'
    result = discover_ir_links(
        "https://example.co.jp/",
        company_html,
        "https://example.co.jp/en/investor/",
        "",
    )
    assert result is not None
    assert "investor" in result["ir_top_url"]


# --- discover_candidates ---

class FakeMetadataNoWebsite:
    def lookup(self, ticker):
        return {"company_name": "Test", "company_site_url": ""}


class FakeMetadata:
    def lookup(self, ticker):
        return {"company_name": "Test Inc.", "company_site_url": "https://example.co.jp/"}


class FakeHttp:
    def __init__(self, company_html=None, ir_html=None):
        self._company = company_html or '<a href="/ir/">投資家情報</a>'
        self._ir = ir_html or '<a href="/ir/library/">IRライブラリー</a>'
        self.calls = []

    def fetch(self, url, allowed_domains, max_bytes):
        self.calls.append(url)
        from safe_http import FetchResult
        if "/ir/library" in url or (self._ir and url.endswith("/ir/")):
            return FetchResult(self._ir.encode("utf-8"), "ok", url, url, "text/html", len(self._ir))
        if "/ir/" in url:
            return FetchResult(self._ir.encode("utf-8"), "ok", url, url, "text/html", len(self._ir))
        return FetchResult(self._company.encode("utf-8"), "ok", url, url, "text/html", len(self._company))


def test_no_candidate_returns_empty_list(tmp_path):
    candidates = discover_candidates("3932", FakeMetadataNoWebsite(), FakeHttp())
    assert candidates == []
    assert list(tmp_path.rglob("*")) == []


def test_discovers_single_candidate():
    candidates = discover_candidates("3932", FakeMetadata(), FakeHttp())
    assert len(candidates) == 1
    c = candidates[0]
    assert c["ticker"] == "3932"
    assert c["company_site_url"] == "https://example.co.jp/"
    assert c["approved_domain"] == "example.co.jp"
    assert len(c["candidate_id"]) == 20


def test_candidate_rediscovery_gets_fresh_candidate_id():
    fake1 = FakeHttp(ir_html='<a href="/ir/library/">IRライブラリー</a>')
    result1 = discover_candidates("3932", FakeMetadata(), fake1)
    fake2 = FakeHttp(ir_html='<a href="/ir/new-library/">New Library</a>')
    result2 = discover_candidates("3932", FakeMetadata(), fake2)
    assert result1[0]["candidate_id"] != result2[0]["candidate_id"]


# --- YahooCompanyMetadataProvider (no network) ---

def test_provider_returns_empty_on_error():
    class BrokenProvider(YahooCompanyMetadataProvider):
        def lookup(self, ticker):
            return {"company_name": "", "company_site_url": ""}
    result = BrokenProvider().lookup("0000")
    assert result["company_name"] == ""
