"""Tests for price tab parser."""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sbi_stock_parser import parse_price, select_price_source

JST = timezone(timedelta(hours=9))


_PRICE_HTML = """
<table>
<tr><th>現在値</th><td>2,150.5<span>円</span><span>06/19 14:30</span></td></tr>
<tr><th>前日比</th><td><span class="up">+35.0</span><span>（+1.65%）</span></td></tr>
<tr><th>始値</th><td>2,130<span>円</span></td></tr>
<tr><th>高値</th><td>2,160<span>円</span></td></tr>
<tr><th>安値</th><td>2,125<span>円</span></td></tr>
<tr><th>前日終値</th><td>2,115.5<span>円</span></td></tr>
<tr><th>出来高</th><td>123,400<span>株</span></td></tr>
<tr><th>売買代金</th><td>265<span>百万円</span></td></tr>
<tr><th>VWAP</th><td>2,148.3<span>円</span></td></tr>
<tr><th>年初来高値</th><td>2,500<span>円</span><span>（2026/01/15）</span></td></tr>
<tr><th>年初来安値</th><td>1,800<span>円</span><span>（2026/03/10）</span></td></tr>
<tr><th>信用売残</th><td>12,000<span>株</span> 前週比 -1,400</td></tr>
<tr><th>信用買残</th><td>45,600<span>株</span> 前週比 +2,300</td></tr>
<tr><th>貸借倍率</th><td>3.80<span>倍</span></td></tr>
<tr><th>予想PER</th><td>15.2<span>倍</span></td></tr>
<tr><th>予想EPS</th><td>141.5<span>円</span></td></tr>
<tr><th>実績PBR</th><td>1.85<span>倍</span></td></tr>
<tr><th>実績BPS</th><td>1,162.4<span>円</span></td></tr>
<tr><th>予想配当利回り</th><td>2.30<span>%</span></td></tr>
<tr><th>予想1株配当</th><td>49.5<span>円</span></td></tr>
</table>
"""

_PRICE_HTML_MISSING = """
<table>
<tr><th>現在値</th><td>－</td></tr>
</table>
"""

_PRICE_HTML_CHANGED = """
<div>まったく異なる構造</div>
"""


def test_parse_price_basic():
    result = parse_price(_PRICE_HTML)
    assert result["status"] == "ok"
    data = result["data"]
    assert data["current_price"] == 2150.5
    assert data["price_change"] == 35.0
    assert data["price_change_percent"] == 1.65
    assert data["open"] == 2130.0
    assert data["high"] == 2160.0
    assert data["low"] == 2125.0
    assert data["previous_close"] == 2115.5
    assert data["volume"] == 123400
    assert data["trading_value_million_yen"] == 265.0
    assert data["vwap"] == 2148.3
    assert data["ytd_high"] == 2500.0
    assert data["ytd_low"] == 1800.0
    assert data["margin_sell_balance"] == 12000
    assert data["margin_buy_balance"] == 45600
    assert data["margin_sell_wow_change"] == -1400
    assert data["margin_buy_wow_change"] == 2300
    assert data["margin_balance_ratio"] == 3.8
    assert data["forward_per"] == 15.2
    assert data["forward_eps"] == 141.5
    assert data["trailing_pbr"] == 1.85
    assert data["trailing_bps"] == 1162.4
    assert data["forward_dividend_yield"] == 2.30
    assert data["forward_dividend_per_share"] == 49.5


def test_parse_price_missing_data():
    result = parse_price(_PRICE_HTML_MISSING)
    assert result["status"] == "not_available"


def test_parse_price_structure_changed():
    result = parse_price(_PRICE_HTML_CHANGED)
    assert result["status"] == "source_changed"


def test_parse_price_empty_html():
    result = parse_price("")
    assert result["status"] == "source_changed"


def test_price_requires_quote_timestamp():
    """Has current_price but no timestamp → source_changed."""
    result = parse_price("<div>現在値 2150.5 円</div>")
    assert result["status"] == "source_changed"


def test_price_ok_with_all_mandatory_fields():
    """Existing fixture has timestamp, must return ok with quote_timestamp."""
    result = parse_price(_PRICE_HTML)
    assert result["status"] == "ok"
    assert "quote_timestamp" in result["data"]
    assert result["data"]["quote_timestamp"] == "2026-06-19T14:30:00+09:00"


def test_unrelated_page_timestamp_does_not_complete_price():
    """Timestamp in news section must NOT satisfy quote_timestamp requirement."""
    html = """
    <table><tr><th>現在値</th><td>1,000円</td></tr></table>
    <div>ニュース更新 06/19 14:30</div>
    """
    result = parse_price(html, as_of=datetime(2026, 6, 20, 12, 0, tzinfo=JST))
    assert result["status"] == "source_changed"
    assert "quote_timestamp" not in result["data"]


def test_price_and_timestamp_must_share_exact_current_price_row():
    """Price value outside price row must not be used as current_price."""
    html = """
    <table><tr><th>現在値</th><td>06/19 14:30</td></tr></table>
    <div>現在値 1,000円</div>
    """
    result = parse_price(html, as_of=datetime(2026, 6, 20, 12, 0, tzinfo=JST))
    assert result["status"] == "source_changed"


def test_current_price_label_must_be_exact():
    """'現在値について' must NOT match; only exact '現在値' should."""
    html = """
    <table>
      <tr><th>現在値について</th><td>06/19 14:30</td></tr>
      <tr><th>現在値</th><td>1,000円 06/19 14:31</td></tr>
    </table>
    """
    result = parse_price(html, as_of=datetime(2026, 6, 20, 12, 0, tzinfo=JST))
    assert result["status"] == "ok"
    assert result["data"]["current_price"] == 1000.0
    assert "14:31" in result["data"]["quote_timestamp"]


def test_stale_quote_timestamp_is_source_changed():
    """Quote timestamp older than 7 days should return source_changed."""
    html = "<table><tr><th>現在値</th><td>1,000円 05/01 14:30</td></tr></table>"
    result = parse_price(html, as_of=datetime(2026, 6, 20, 12, 0, tzinfo=JST))
    assert result["status"] == "source_changed"


def test_sub_100_yen_price():
    """Prices below 100 yen must be extractable (e.g., 98円, 98.5円)."""
    html = "<table><tr><th>現在値</th><td>98.5円 06/19 14:30</td></tr></table>"
    result = parse_price(html, as_of=datetime(2026, 6, 20, 12, 0, tzinfo=JST))
    assert result["status"] == "ok"
    assert result["data"]["current_price"] == 98.5


def test_strict_7_day_boundary():
    """7 days + 1 hour must be rejected (not rounded to 7 days)."""
    from datetime import timedelta
    ref = datetime(2026, 6, 20, 12, 0, tzinfo=JST)
    # 7 days 1 hour ago
    stale_dt = ref - timedelta(days=7, hours=1)
    ts = stale_dt.strftime("%m/%d %H:%M")
    html = f"<table><tr><th>現在値</th><td>1,000円 {ts}</td></tr></table>"
    result = parse_price(html, as_of=ref)
    assert result["status"] == "source_changed"


def test_price_source_arbitration_prefers_tab():
    tab = {"status": "ok", "data": {"current_price": 1000.0, "quote_timestamp": "2026-06-20T14:30:00+09:00"}}
    result = select_price_source(tab, 1100.0, "2026-06-20T15:00:00+09:00", "2026-06-20T15:00:00+09:00")
    assert result["status"] == "ok"
    assert result["data"]["current_price"] == 1000.0
    assert result["data"]["source_kind"] == "price_tab"


def test_price_source_falls_back_to_api():
    tab = {"status": "source_changed", "data": {"high": 3390.0}}
    result = select_price_source(tab, 108600.0, "2026-06-20T10:00:00+09:00", "2026-06-20T15:00:00+09:00")
    assert result["status"] == "ok"
    assert result["data"]["current_price"] == 108600.0
    assert result["data"]["source_kind"] == "analysis_api"
