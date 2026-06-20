"""Tests for company profile (四季報) tab parser."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sbi_stock_parser import parse_company_profile


_PROFILE_HTML = """
<div class="shikiho">
  <div>作成日：2026年06月17日</div>
  <div>アカツキ （3932） ［ 情報・通信業 ］</div>
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

# Different article labels — tags vary per company (not always 【連続増配】【経営統合】)
_PROFILE_HTML_ALT_LABELS = """
<div class="shikiho">
  <div>作成日：2026年06月17日</div>
  <div>トヨタ自動車 （7203） ［ 輸送用機器 ］</div>
  <div>【特色】自動車製造販売を主力とする世界的企業。</div>
  <div>【連結事業】自動車90、金融8、その他2</div>
  <div>【業績回復】北米販売が好調で営業益は増加。</div>
  <div>【海外展開】EVシフトを加速、2026年までに30モデル投入予定。</div>
  <div>【業種】 輸送用機器 時価総額順位 1/85社</div>
  <div>【比較会社】7267 ホンダ,7270 SUBARU</div>
</div>
"""


def test_parse_company_profile_different_article_labels():
    result = parse_company_profile(_PROFILE_HTML_ALT_LABELS)
    assert result["status"] == "ok"
    data = result["data"]
    assert data["company_name"] == "トヨタ自動車"
    assert "自動車製造販売" in data["characteristics"]
    assert "北米販売が好調" in data["performance_summary"]
    assert "EVシフト" in data["material_notes"]
    assert data["sector"] == "輸送用機器"


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


def test_profile_requires_core_fields():
    """Missing company_name, characteristics, business_segments → source_changed."""
    result = parse_company_profile("<div>作成日：2026年06月17日</div>")
    assert result["status"] == "source_changed"


# Sanitized 285A profile structure
_PROFILE_285A_HTML = """
<div class="shikiho">
  <div>作成日：2026年06月17日</div>
  <div>キオクシアホールディングス （285A） ［ 電子部品・産業用電子機器 ］</div>
  <div>【ＵＲＬ】https://www.example.com/</div>
  <div>【決算】3月</div>
  <div>【設立】2019.3</div>
  <div>【上場】2024.12</div>
  <div>【特色】半導体メモリー専業の世界大手</div>
  <div>【連結事業】SSD&ストレージ58、スマートデバイス33</div>
  <div>【海外】89</div>
  <div>【爆　益】生成ＡＩ需要の活況が追い風</div>
  <div>【台　湾】ＤＲＡＭメーカーに770億円出資</div>
  <div>【業種】 電子部品・産業用電子機器 時価総額順位 1/220社</div>
  <div>【比較会社】6723 ルネサスエ</div>
</div>
"""


def test_285A_profile_company_name():
    result = parse_company_profile(_PROFILE_285A_HTML)
    assert result["status"] == "ok"
    data = result["data"]
    assert data["company_name"] == "キオクシアホールディングス"
    assert data["overseas_ratio"] == "89"
    assert "生成ＡＩ需要" in data["performance_summary"]
    assert "ＤＲＡＭ" in data["material_notes"]
    assert data["sector"] == "電子部品・産業用電子機器"
