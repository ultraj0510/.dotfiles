from datetime import date

from fixtures import TABLE_HTML, CARD_HTML, ARCHIVE_HTML, JS_ONLY_HTML

from document_index import scan_index, _extract_date


class FakeHttpClient:
    def __init__(self, pages=None):
        self._pages = pages or {}
        self.calls = []

    def add(self, url, html):
        self._pages[url] = html

    def fetch(self, url, allowed_domains, max_bytes):
        self.calls.append(url)
        from safe_http import FetchResult
        html = self._pages.get(url, "")
        if html:
            return FetchResult(html.encode("utf-8"), "ok", url, url, "text/html", len(html))
        return FetchResult(None, "not_found", url, url, "", 0)


def test_scan_index_extracts_table_entries():
    http = FakeHttpClient({"https://example.co.jp/ir/": TABLE_HTML})
    result = scan_index(
        "https://example.co.jp/ir/",
        date(2026, 1, 1), date(2026, 12, 31),
        "example.co.jp", http,
    )
    assert len(result["entries"]) >= 2
    assert result["status"] == "ok"


def test_scan_index_extracts_card_entries():
    http = FakeHttpClient({"https://example.co.jp/ir/": CARD_HTML})
    result = scan_index(
        "https://example.co.jp/ir/",
        date(2025, 1, 1), date(2025, 12, 31),
        "example.co.jp", http,
    )
    assert len(result["entries"]) >= 1


def test_scan_index_follows_archive_links():
    http = FakeHttpClient({
        "https://example.co.jp/ir/": ARCHIVE_HTML,
        "https://example.co.jp/ir/library/": TABLE_HTML,
    })
    result = scan_index(
        "https://example.co.jp/ir/",
        date(2026, 1, 1), date(2026, 12, 31),
        "example.co.jp", http,
    )
    assert len(result["visited_pages"]) >= 2


def test_scan_index_js_only_marks_unsupported():
    http = FakeHttpClient({"https://example.co.jp/ir/": JS_ONLY_HTML})
    result = scan_index(
        "https://example.co.jp/ir/",
        date(2026, 1, 1), date(2026, 12, 31),
        "example.co.jp", http,
    )
    assert result["status"] == "unsupported"


def test_scan_index_filters_by_date_window():
    http = FakeHttpClient({"https://example.co.jp/ir/": TABLE_HTML})
    result = scan_index(
        "https://example.co.jp/ir/",
        date(2030, 1, 1), date(2030, 12, 31),
        "example.co.jp", http,
    )
    assert len(result["entries"]) == 0


def test_scan_respects_max_pages():
    http = FakeHttpClient({})
    http._pages["https://example.co.jp/ir/"] = '<a href="/ir/past/2025/">past 2025</a><a href="/ir/past/2024/">past 2024</a><a href="/ir/past/2023/">past 2023</a>'
    result = scan_index(
        "https://example.co.jp/ir/",
        date(2026, 1, 1), date(2026, 12, 31),
        "example.co.jp", http, max_pages=2,
    )
    assert not result["complete"]
    assert len(result["visited_pages"]) <= 2


def test_extract_date_japanese():
    assert _extract_date("2026年5月10日") == "2026-05-10"


def test_extract_date_slash():
    assert _extract_date("2026/05/10") == "2026-05-10"


def test_extract_date_dash():
    assert _extract_date("2026-05-10") == "2026-05-10"


def test_extract_date_dot():
    assert _extract_date("2026.05.10") == "2026-05-10"


def test_extract_date_invalid():
    assert _extract_date("99年1月1日") == ""
