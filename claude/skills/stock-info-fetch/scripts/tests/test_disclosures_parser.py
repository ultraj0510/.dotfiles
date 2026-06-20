"""Tests for disclosures tab parser."""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sbi_stock_parser import parse_disclosures

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
    result = parse_disclosures(_DISCLOSURES_HTML, as_of=datetime(2026, 6, 19, tzinfo=JST))
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
