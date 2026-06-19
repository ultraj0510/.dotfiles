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
