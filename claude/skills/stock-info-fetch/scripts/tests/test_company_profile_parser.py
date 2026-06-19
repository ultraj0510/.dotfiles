"""Tests for company profile (四季報) tab parser."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sbi_stock_parser import parse_company_profile


_PROFILE_HTML = """
<div class="shikiho">
  <div>作成日：2026年06月17日</div>
  <div>3932 (株)アカツキ ［ 情報・通信業 ］</div>
  <div>【ＵＲＬ】https://www.example.co.jp/</div>
  <div>【決算】3月</div>
  <div>【設立】2010.6</div>
  <div>【上場】2016.3</div>
  <div>【特色】ゲーム開発・運営を主力とするIT企業。</div>
  <div>【連結事業】ゲーム85、広告10、その他5</div>
  <div>【連続増配】新作ゲームのヒットにより営業益は増加。</div>
  <div>【経営統合】海外展開を加速。</div>
  <div>【業種】 通信サービス 時価総額順位 18/103社</div>
  <div>【比較会社】3668 コロプラ,3662 AチームH,3656 KLab</div>
</div>
"""

_PROFILE_HTML_EMPTY = "<div>四季報情報はありません</div>"

_PROFILE_HTML_CHANGED = "<div>unrecognizable structure</div>"


def test_parse_company_profile_basic():
    result = parse_company_profile(_PROFILE_HTML)
    assert result["status"] == "ok"
    data = result["data"]
    assert data["company_name"] == "アカツキ"
    assert data["report_date"] == "2026-06-17"
    assert data["company_url"] == "https://www.example.co.jp"
    assert data["fiscal_month"] == "3月"
    assert data["established"] == "2010.6"
    assert data["listed"] == "2016.3"
    assert "ゲーム開発" in data["characteristics"]
    assert "ゲーム85" in data["business_segments"]
    assert "新作ゲームのヒット" in data["performance_summary"]
    assert "海外展開を加速" in data["material_notes"]
    assert data["sector"] == "通信サービス"
    assert data["sector_rank"] == "18/103社"
    assert "コロプラ" in data["peer_companies"]


def test_parse_company_profile_not_available():
    result = parse_company_profile(_PROFILE_HTML_EMPTY)
    assert result["status"] == "not_available"


def test_parse_company_profile_structure_changed():
    result = parse_company_profile(_PROFILE_HTML_CHANGED)
    assert result["status"] == "source_changed"
