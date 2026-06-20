"""Tests for performance (STOCK REPORTS HTML) parser."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sbi_stock_parser import parse_performance

_PERFORMANCE_HTML = """
<table>
<tr><th></th><th>1Q</th><th>2Q</th><th>3Q</th><th>通期</th></tr>
<tr><th>2027/03 コンセンサス予想</th><td>240</td><td>--</td><td>--</td><td>11,000</td></tr>
<tr><th>2026/03 会社実績（前期進捗率）</th><td>-1,907 (--%)</td><td>1,676 (--%)</td><td>3,318 (--%)</td><td>7,618 (--%)</td></tr>
</table>
<table>
<tr><th>最新値</th><th>1週間前</th><th>1ヶ月前</th><th>3ヶ月前</th></tr>
<tr><td>5.00</td><td>5.00</td><td>5.00</td><td>5.00</td></tr>
</table>
<table>
<tr><th>強気 (5点)</th><td>1人</td></tr>
<tr><th>中立 (3点)</th><td>0人</td></tr>
</table>
<table>
<tr><th>最新値</th><th>対前週変化率</th><th>かい離率</th></tr>
<tr><td>3,390円</td><td>0.00%</td><td>20.34%</td></tr>
</table>
"""


def test_parse_performance():
    result = parse_performance(_PERFORMANCE_HTML)
    assert result["status"] == "ok"
    data = result["data"]
    assert data["periods"] == ["1Q", "2Q", "3Q", "通期"]
    assert data["actual_results"][0]["fiscal_period"] == "2026/03"
    assert data["actual_results"][0]["values"]["通期"]["value"] == 7618.0
    assert data["consensus_forecast"][0]["values"]["通期"]["value"] == 11000.0
    assert data["rating_current"] == 5.0
    assert data["rating_distribution"]["strong"] == 1
    assert data["target_price_consensus"] == 3390.0
    assert data["target_price_wow_change_pct"] == 0.0
    assert data["target_price_vs_market_pct"] == 20.34


def test_parse_performance_not_available():
    result = parse_performance("<div>業績情報はありません</div>")
    assert result["status"] == "not_available"


def test_parse_performance_source_changed():
    result = parse_performance("<div>garbage</div>")
    assert result["status"] == "source_changed"


def test_all_dash_row_not_counted_as_extracted():
    """Rows where all 4 periods are '--' must not appear in output arrays."""
    html = """
    <table>
    <tr><th></th><th>1Q</th><th>2Q</th><th>3Q</th><th>通期</th></tr>
    <tr><th>2027/03 会社予想</th><td>--</td><td>--</td><td>--</td><td>--</td></tr>
    </table>
    """
    result = parse_performance(html)
    assert result["status"] == "source_changed"


def test_unknown_row_type_not_counted_as_extracted():
    """Row with values but unknown type label (市場予想) must not increment extracted."""
    html = """
    <table>
    <tr><th></th><th>1Q</th><th>2Q</th><th>3Q</th><th>通期</th></tr>
    <tr><th>2027/03 市場予想</th><td>240</td><td>--</td><td>--</td><td>11,000</td></tr>
    </table>
    """
    result = parse_performance(html)
    assert result["status"] == "source_changed"


def test_unknown_row_alongside_known_row_is_source_changed():
    """Mixed: known row + unknown row (市場予想) → source_changed with partial data."""
    html = """
    <table>
    <tr><th></th><th>1Q</th><th>2Q</th><th>3Q</th><th>通期</th></tr>
    <tr><th>2026/03 会社実績</th><td>-1,907</td><td>1,676</td><td>3,318</td><td>7,618</td></tr>
    <tr><th>2027/03 市場予想</th><td>240</td><td>--</td><td>--</td><td>11,000</td></tr>
    </table>
    """
    result = parse_performance(html)
    assert result["status"] == "source_changed"
    # Known row data is preserved
    assert len(result["data"]["actual_results"]) == 1
    assert result["data"]["actual_results"][0]["values"]["通期"]["value"] == 7618.0


def test_rating_distribution_preserved_on_source_changed():
    """When only rating distribution is found, data must be preserved."""
    html = """
    <table>
    <tr><th>強気 (5点)</th><td>3人</td></tr>
    <tr><th>中立 (3点)</th><td>2人</td></tr>
    </table>
    """
    result = parse_performance(html)
    assert result["status"] == "source_changed"
    assert result["data"]["rating_distribution"]["strong"] == 3
    assert result["data"]["rating_distribution"]["neutral"] == 2


def test_all_dash_row_excluded_when_real_row_present():
    """Mix: one real row, one all-dash row. Dash row must be absent from output."""
    html = """
    <table>
    <tr><th></th><th>1Q</th><th>2Q</th><th>3Q</th><th>通期</th></tr>
    <tr><th>2026/03 会社実績</th><td>-1,907</td><td>1,676</td><td>3,318</td><td>7,618</td></tr>
    <tr><th>2027/03 会社予想</th><td>--</td><td>--</td><td>--</td><td>--</td></tr>
    </table>
    """
    result = parse_performance(html)
    assert result["status"] == "ok"
    assert len(result["data"]["actual_results"]) == 1
    assert len(result["data"]["company_forecast"]) == 0


def test_rating_distro_no_fabricated_zero():
    """When regex doesn't match, don't add key at all (no fabricated 0)."""
    html = "<table><tr><th>強気 (5点)</th><td>不明</td></tr></table>"
    result = parse_performance(html)
    assert "strong" not in result["data"].get("rating_distribution", {})
