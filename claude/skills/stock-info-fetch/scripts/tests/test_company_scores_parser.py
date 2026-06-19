"""Tests for company scores parser."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sbi_stock_parser import parse_company_scores


_SCORES_HTML = """
<table>
<tr><th>企業スコア総合</th><td>6.0</td></tr>
<tr><th>財務健全性</th><td>7.0</td></tr>
<tr><th>収益性</th><td>5.0</td></tr>
<tr><th>割安性</th><td>8.0</td></tr>
<tr><th>安定性</th><td>3.0</td></tr>
<tr><th>株価モメンタム</th><td>6.0</td></tr>
</table>
"""


def test_parse_company_scores():
    result = parse_company_scores(_SCORES_HTML)
    assert result["status"] == "ok"
    data = result["data"]
    assert data["total_score"] == 6.0
    assert data["financial_health"] == 7.0
    assert data["profitability"] == 5.0
    assert data["valuation"] == 8.0
    assert data["stability"] == 3.0
    assert data["price_momentum"] == 6.0


def test_parse_company_scores_not_available():
    result = parse_company_scores("<div>スコア情報はありません</div>")
    assert result["status"] == "not_available"


def test_parse_company_scores_structure_changed():
    result = parse_company_scores("<div>unrecognizable</div>")
    assert result["status"] == "source_changed"


def test_parse_company_scores_below_threshold():
    """Only 2 of 6 scores extracted — should be source_changed."""
    html = """
    <table>
    <tr><th>企業スコア総合</th><td>5.0</td></tr>
    <tr><th>財務健全性</th><td>6.0</td></tr>
    </table>
    """
    result = parse_company_scores(html)
    assert result["status"] == "source_changed"
    assert result["data"]["total_score"] == 5.0


def test_parse_company_scores_out_of_range():
    """Scores outside 1-10 must be source_changed."""
    html = """
    <table>
    <tr><th>企業スコア総合</th><td>0.0</td></tr>
    <tr><th>財務健全性</th><td>0.0</td></tr>
    <tr><th>収益性</th><td>0.0</td></tr>
    </table>
    """
    result = parse_company_scores(html)
    assert result["status"] == "source_changed"
