from datetime import date

from fixtures import (
    TABLE_HTML, CARD_HTML, ARCHIVE_HTML, JS_ONLY_HTML,
    KIOXIA_NEWS_CARD_HTML, KIOXIA_EVENT_GROUP_HTML, DISTANT_DATE_SECTION_HTML,
)

from document_index import scan_index, _extract_date, _extract_dates


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


def test_scan_extracts_date_from_outer_news_card():
    http = FakeHttpClient({
        "https://example.co.jp/ir/news.html": KIOXIA_NEWS_CARD_HTML,
    })
    result = scan_index(
        ["https://example.co.jp/ir/news.html"],
        date(2026, 1, 1),
        date(2026, 12, 31),
        "example.co.jp",
        http,
    )
    assert [(e["published_at"], e["title"]) for e in result["entries"]] == [
        ("2026-05-15", "2026年3月期 決算短信")
    ]


def test_scan_associates_group_heading_date_with_event_pdfs():
    http = FakeHttpClient({
        "https://example.co.jp/ir/event.html": KIOXIA_EVENT_GROUP_HTML,
    })
    result = scan_index(
        ["https://example.co.jp/ir/event.html"],
        date(2026, 1, 1),
        date(2026, 12, 31),
        "example.co.jp",
        http,
    )
    assert len(result["entries"]) == 3
    assert {e["published_at"] for e in result["entries"]} == {"2026-06-02"}


def test_scan_does_not_attach_distant_section_date():
    http = FakeHttpClient({
        "https://example.co.jp/ir/event.html": DISTANT_DATE_SECTION_HTML,
    })
    result = scan_index(
        ["https://example.co.jp/ir/event.html"],
        date(2026, 1, 1),
        date(2026, 12, 31),
        "example.co.jp",
        http,
    )
    assert result["entries"] == []
