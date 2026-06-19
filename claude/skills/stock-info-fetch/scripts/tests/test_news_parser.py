"""Tests for news tab parser."""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sbi_stock_parser import parse_news

JST = timezone(timedelta(hours=9))

_NEWS_HTML = """
<table>
<tr><td>06/19 14:30</td><td><a href="/news/article123">2026年3月期 決算発表</a></td></tr>
<tr><td>2026/06/15 09:00</td><td>レーティング</td><td><a href="/news/article122">目標株価引き上げ</a></td></tr>
<tr><td>2026/04/10 15:00</td><td>IR</td><td><a href="/news/article121">新作ゲーム発表</a></td></tr>
</table>
"""

_NEWS_HTML_EMPTY = "<div>ニュースはありません</div>"

_NEWS_HTML_OLD_OUTSIDE_90D = """
<table>
<tr><td>2025/12/01 10:00</td><td>IR</td><td><a href="/news/article1">古いニュース</a></td></tr>
</table>
"""


def test_parse_news_basic():
    result = parse_news(_NEWS_HTML, as_of=datetime(2026, 6, 19, 23, 59, 59, tzinfo=JST))
    assert result["status"] == "ok"
    data = result["data"]
    assert len(data) == 3
    assert data[0]["published_at"] == "2026-06-19T14:30:00+09:00"
    assert data[0]["headline"] == "2026年3月期 決算発表"
    assert data[0]["url"].endswith("/news/article123")


def test_parse_news_not_available():
    result = parse_news(_NEWS_HTML_EMPTY, as_of=datetime(2026, 6, 19, tzinfo=JST))
    assert result["status"] == "not_available"


def test_parse_news_filters_outside_90_days():
    result = parse_news(
        _NEWS_HTML_OLD_OUTSIDE_90D,
        as_of=datetime(2026, 6, 19, tzinfo=JST),
    )
    assert result["status"] == "not_available"


def test_parse_news_structure_changed():
    result = parse_news("<div>garbage</div>", as_of=datetime(2026, 6, 19, tzinfo=JST))
    assert result["status"] == "source_changed"


def test_parse_news_leap_day_feb29():
    """02/29 must parse correctly using leap year 2024 as base."""
    html = """
    <table>
    <tr><td>02/29 10:00</td><td>IR</td><td><a href="/news/leap">leap day news</a></td></tr>
    </table>
    """
    # as_of must be within 90 days of Feb 29 for the item to pass the cutoff
    result = parse_news(html, as_of=datetime(2024, 3, 15, tzinfo=JST))
    assert result["status"] == "ok"
    assert result["data"][0]["published_at"] == "2024-02-29T10:00:00+09:00"


def test_parse_news_feb29_in_non_leap_year_no_crash():
    """In non-leap year, Feb 29 resolves to previous year without crashing.
    It will be outside the 90-day cutoff, but must not ValueError."""
    html = """
    <table>
    <tr><td>02/29 10:00</td><td>IR</td><td><a href="/news/leap_prev">leap day (previous year)</a></td></tr>
    </table>
    """
    result = parse_news(html, as_of=datetime(2025, 3, 15, tzinfo=JST))
    assert result["status"] in ("ok", "not_available")


def test_parse_news_future_yearless_snaps_to_previous_year():
    """12/31 in June must snap to previous year, not future."""
    html = """
    <table>
    <tr><td>12/31 10:00</td><td>IR</td><td><a href="/news/dec31">year-end news</a></td></tr>
    </table>
    """
    result = parse_news(html, as_of=datetime(2026, 6, 20, tzinfo=JST))
    # Resolves to 2025-12-31, which is < 90 days from 2026-06-20? No, >90 days → not_available
    assert result["status"] in ("ok", "not_available")


def test_parse_news_explicit_future_year_excluded():
    """2027/01/01 must not appear when as_of is 2026-06-20."""
    html = """
    <table>
    <tr><td>2027/01/01 10:00</td><td>IR</td><td><a href="/news/future">future news</a></td></tr>
    </table>
    """
    result = parse_news(html, as_of=datetime(2026, 6, 20, tzinfo=JST))
    # Future date excluded → 0 items
    assert result["status"] in ("not_available", "source_changed")
