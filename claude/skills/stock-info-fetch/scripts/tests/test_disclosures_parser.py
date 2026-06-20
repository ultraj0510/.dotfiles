"""Tests for disclosures tab parser."""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sbi_stock_parser import parse_disclosures, parse_disclosure_cards

JST = timezone(timedelta(hours=9))


_DISCLOSURES_HTML = """
<table>
<tr><td>2026/06/19 15:00</td><td>決算短信</td><td><a href="/disclosure/tdnet/abc123.pdf">2026年3月期 決算短信〔日本基準〕（連結）</a></td></tr>
<tr><td>2026/05/15 16:30</td><td>自己株</td><td><a href="/disclosure/tdnet/abc122.pdf">自己株式取得に係る事項の決定に関するお知らせ</a></td></tr>
<tr><td>2025/07/01 09:00</td><td>適時開示</td><td><a href="/disclosure/tdnet/abc100.pdf">新作ゲームのリリースに関するお知らせ</a></td></tr>
</table>
"""

_DISCLOSURES_HTML_EMPTY = "<div>適時開示はありません</div>"


def test_parse_disclosures_basic():
    result = parse_disclosures(_DISCLOSURES_HTML, as_of=datetime(2026, 6, 19, 15, 30, tzinfo=JST))
    assert result["status"] == "ok"
    data = result["data"]
    assert len(data) == 3
    assert data[0]["published_at"] == "2026-06-19T15:00:00+09:00"
    assert data[0]["category"] == "決算短信"
    assert "決算短信" in data[0]["title"]
    assert data[0]["url"].endswith(".pdf")


def test_parse_disclosures_not_available():
    result = parse_disclosures(_DISCLOSURES_HTML_EMPTY, as_of=datetime(2026, 6, 19, tzinfo=JST))
    assert result["status"] == "not_available"


def test_parse_disclosures_filters_outside_1_year():
    result = parse_disclosures(
        '<table><tr><td>2024/01/01 10:00</td><td>IR</td><td><a href="/old.pdf">古い開示</a></td></tr></table>',
        as_of=datetime(2026, 6, 19, tzinfo=JST),
    )
    assert result["status"] == "not_available"


def test_parse_disclosures_structure_changed():
    result = parse_disclosures("<div>unknown</div>", as_of=datetime(2026, 6, 19, tzinfo=JST))
    assert result["status"] == "source_changed"


def test_disclosures_excludes_future_items():
    """Disclosures dated after as_of must be excluded."""
    html = '<table><tr><td>2026/12/01 10:00</td><td>IR</td><td><a href="/future.pdf">未来の開示</a></td></tr></table>'
    result = parse_disclosures(html, as_of=datetime(2026, 6, 20, tzinfo=JST))
    assert result["status"] in ("not_available", "source_changed")
    assert result["data"] == []


def test_disclosures_excludes_same_day_future_time():
    """Disclosure at 23:00 when as_of is 12:00 must be excluded."""
    JST = timezone(timedelta(hours=9))
    html = "<table><tr><td>2026/06/20 23:00</td><td>IR</td><td><a href='/x.pdf'>x</a></td></tr></table>"
    result = parse_disclosures(html, as_of=datetime(2026, 6, 20, 12, 0, tzinfo=JST))
    assert result["data"] == []


_DISCLOSURE_CARDS_HTML = """
<div id="disclo_report">
  <div class="line">
    <span class="date">2026/06/20 15:00</span>
    <span class="category">決算短信</span>
    <a href="/disclosure/abc.pdf">決算短信テスト</a>
  </div>
  <div class="line">
    <span class="date">2026/05/15 16:30</span>
    <span class="category">自己株</span>
    <a href="/disclosure/def.pdf">自己株式取得</a>
  </div>
</div>
"""


def test_parse_disclosure_cards_basic():
    result = parse_disclosure_cards(_DISCLOSURE_CARDS_HTML, as_of=datetime(2026, 6, 20, 23, 59, tzinfo=JST))
    assert result["status"] == "ok"
    assert len(result["data"]) == 2
    assert result["data"][0]["title"] == "決算短信テスト"
    assert result["data"][0]["published_at"] == "2026-06-20T15:00:00+09:00"
    assert result["data"][0]["category"] == "決算短信"
    assert result["data"][1]["title"] == "自己株式取得"


def test_parse_disclosure_cards_falls_back_to_tables():
    """When HTML uses <table> instead of .line divs, fall back to parse_disclosures."""
    table_html = (
        '<table><tr><td>2026/06/19 15:00</td><td>決算短信</td>'
        '<td><a href="/disclosure/a.pdf">開示</a></td></tr></table>'
    )
    result = parse_disclosure_cards(table_html, as_of=datetime(2026, 6, 19, 15, 30, tzinfo=JST))
    assert result["status"] == "ok"
    assert len(result["data"]) == 1


def test_parse_disclosure_cards_not_available():
    """Explicit no-data marker must return not_available."""
    html = "<div>適時開示はありません</div>"
    result = parse_disclosure_cards(html, as_of=datetime(2026, 6, 20, tzinfo=JST))
    assert result["status"] == "not_available"
    assert result["data"] == []


def test_parse_disclosure_cards_source_changed():
    """Unknown structure must return source_changed."""
    html = "<div>まったく関係ない内容</div>"
    result = parse_disclosure_cards(html, as_of=datetime(2026, 6, 20, tzinfo=JST))
    assert result["status"] == "source_changed"
    assert result["data"] == []
