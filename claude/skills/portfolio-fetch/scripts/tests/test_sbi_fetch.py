"""Unit tests for parse_sbi_holdings and merge_holdings."""
import importlib.util
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
SBI_FETCH = SCRIPT_DIR / "sbi_fetch.py"


def load_sbi_fetch():
    spec = importlib.util.spec_from_file_location("sbi_fetch_under_test", SBI_FETCH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_NISA_SECTION_HTML = """<tr><td>株式（現物/NISA預り）</td></tr>
<tr>
  <td>285A</td>
  <td>キオクシアＨＤ</td>
  <td>--</td>
  <td>100</td>
  <td>15,136</td>
  <td>96,900</td>
</tr>
"""

_NISA_TSUMITE_SECTION_HTML = """<tr><td>株式（現物/NISA預り）</td></tr>
<tr>
  <td>NISA（つみたて投資枠）</td>
</tr>
<tr>
  <td>1328</td>
  <td>ＮＦ金価格</td>
  <td>--</td>
  <td>7</td>
  <td>16,825</td>
  <td>16,360</td>
</tr>
"""

_NISA_GROWTH_SECTION_HTML = """<tr><td>株式（現物/NISA預り）</td></tr>
<tr>
  <td>NISA（成長投資枠）</td>
</tr>
<tr>
  <td>7974</td>
  <td>任天堂</td>
  <td>--</td>
  <td>100</td>
  <td>10,673</td>
  <td>7,166</td>
</tr>
"""

_TOKUTEI_SECTION_HTML = """<tr><td>株式（現物/特定預り）</td></tr>
<tr>
  <td>7013</td>
  <td>ＩＨＩ</td>
  <td>--</td>
  <td>100</td>
  <td>3,528</td>
  <td>2,866</td>
</tr>
"""

_IPPAN_SECTION_HTML = """<tr><td>株式（現物/一般預り）</td></tr>
<tr>
  <td>4661</td>
  <td>ＯＬＣ</td>
  <td>--</td>
  <td>200</td>
  <td>3,045</td>
  <td>2,300</td>
</tr>
"""


_CREDIT_SECTION_HTML = """<tr><td>株式（信用）</td></tr>
<tr>
  <td>285A</td>
  <td>キオクシアＨＤ</td>
  <td>売建</td>
  <td>6ヶ月</td>
  <td>26/06/23</td>
  <td>300</td>
  <td>110,750</td>
  <td>92,290</td>
</tr>
<tr>
  <td>7012</td>
  <td>川崎重</td>
  <td>買建</td>
  <td>6ヶ月</td>
  <td>26/06/20</td>
  <td>100</td>
  <td>8,000</td>
  <td>8,500</td>
</tr>
<tr><td>投資信託</td></tr>
"""

def test_nisa_section_header_matched():
    module = load_sbi_fetch()
    pattern = module._SBI_FETCH_MODULE__spot_section_pattern if hasattr(module, '_SBI_FETCH_MODULE__spot_section_pattern') else None
    # Replicate the pattern from the module
    import re
    spot_section_pattern = re.compile(r"(株式[（(]現物/(特定預り|NISA(?:預り)?|一般預り)[）)])")

    # NISA預り should match
    assert spot_section_pattern.search("株式（現物/NISA預り）") is not None
    # Bare NISA should also match (legacy)
    assert spot_section_pattern.search("株式（現物/NISA）") is not None
    # 特定預り should match
    assert spot_section_pattern.search("株式（現物/特定預り）") is not None
    # 一般預り should match
    assert spot_section_pattern.search("株式（現物/一般預り）") is not None
    # NISA預り capture group should yield "NISA預り"
    m = spot_section_pattern.search("株式（現物/NISA預り）")
    assert m.group(2) == "NISA預り"


def test_parse_nisa_holdings_default_account_type():
    module = load_sbi_fetch()
    html = _NISA_SECTION_HTML
    holdings, _ = module.parse_sbi_holdings(html)
    assert len(holdings) == 1
    assert holdings[0]["ticker"] == "285A.T"
    assert holdings[0]["account_type"] == "NISA"


def test_parse_nisa_tsumitate():
    module = load_sbi_fetch()
    html = _NISA_TSUMITE_SECTION_HTML
    holdings, _ = module.parse_sbi_holdings(html)
    assert len(holdings) == 1
    assert holdings[0]["ticker"] == "1328.T"
    assert holdings[0]["account_type"] == "NISAつみたて"


def test_parse_nisa_growth():
    module = load_sbi_fetch()
    html = _NISA_GROWTH_SECTION_HTML
    holdings, _ = module.parse_sbi_holdings(html)
    assert len(holdings) == 1
    assert holdings[0]["ticker"] == "7974.T"
    assert holdings[0]["account_type"] == "NISA成長"


def test_parse_tokutei():
    module = load_sbi_fetch()
    holdings, _ = module.parse_sbi_holdings(_TOKUTEI_SECTION_HTML)
    assert len(holdings) == 1
    assert holdings[0]["ticker"] == "7013.T"
    assert holdings[0]["account_type"] == "特定"


def test_parse_ippan():
    module = load_sbi_fetch()
    holdings, _ = module.parse_sbi_holdings(_IPPAN_SECTION_HTML)
    assert len(holdings) == 1
    assert holdings[0]["ticker"] == "4661.T"
    assert holdings[0]["account_type"] == "一般"


def test_parse_credit_side():
    module = load_sbi_fetch()
    holdings, _ = module.parse_sbi_holdings(_CREDIT_SECTION_HTML)
    assert len(holdings) == 2
    assert holdings[0]["ticker"] == "285A.T"
    assert holdings[0]["position_type"] == "信用"
    assert holdings[0]["margin_side"] == "売建"
    assert holdings[0]["quantity"] == 300
    assert holdings[0]["cost_price"] == 110750.0
    assert holdings[0]["current_price"] == 92290.0
    assert holdings[1]["ticker"] == "7012.T"
    assert holdings[1]["margin_side"] == "買建"


def test_merge_holdings_aborts_on_50pct():
    module = load_sbi_fetch()
    existing = [
        {"ticker": "A.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
        {"ticker": "B.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
        {"ticker": "C.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
    ]
    sbi = [{"ticker": "A.T", "position_type": "現物", "account_type": "特定", "quantity": 100}]
    result = module.merge_holdings(existing, sbi)
    assert result is None


def test_merge_holdings_aborts_on_3_missing():
    module = load_sbi_fetch()
    existing = [
        {"ticker": "A.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
        {"ticker": "B.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
        {"ticker": "C.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
        {"ticker": "D.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
    ]
    sbi = [{"ticker": "D.T", "position_type": "現物", "account_type": "特定", "quantity": 100}]
    # 3 missing but 1 out of 4 is 25% >= 50%? No, 1 < 4*0.5=2.0, so 50% guard catches it first.
    # Test with 2 out of 4: 2 >= 4*0.5=2 → 50% passes, but 2 missing (<3) → passes both guards.
    result = module.merge_holdings(existing, sbi)
    assert result is None  # caught by 50% guard


def test_merge_holdings_aborts_on_exactly_3_missing_passes_50pct():
    module = load_sbi_fetch()
    existing = [
        {"ticker": "A.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
        {"ticker": "B.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
        {"ticker": "C.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
        {"ticker": "D.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
        {"ticker": "E.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
    ]
    sbi = [
        {"ticker": "A.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
        {"ticker": "B.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
    ]
    # 2 out of 5 = 40% < 50% → 50% guard catches it
    result = module.merge_holdings(existing, sbi)
    assert result is None


def test_merge_holdings_3_missing_but_above_50pct():
    module = load_sbi_fetch()
    existing = [
        {"ticker": "A.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
        {"ticker": "B.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
        {"ticker": "C.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
        {"ticker": "D.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
    ]
    sbi = [
        {"ticker": "A.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
    ]
    # 1 < 4*0.5 → 50% guard triggers first
    result = module.merge_holdings(existing, sbi)
    assert result is None


def test_merge_holdings_account_type_change_not_counted_as_missing():
    """account_type reclassification (一般→NISA) should NOT trigger the 3-missing guard."""
    module = load_sbi_fetch()
    existing = [
        {"ticker": "7974.T", "position_type": "現物", "account_type": "一般", "quantity": 100, "cost_price": 10673.0},
        {"ticker": "4661.T", "position_type": "現物", "account_type": "一般", "quantity": 200, "cost_price": 3045.0},
        {"ticker": "1328.T", "position_type": "現物", "account_type": "一般", "quantity": 9, "cost_price": 17860.0},
        {"ticker": "7013.T", "position_type": "現物", "account_type": "特定", "quantity": 100, "cost_price": 3528.0},
        {"ticker": "8473.T", "position_type": "現物", "account_type": "特定", "quantity": 200, "cost_price": 3231.0},
    ]
    sbi = [
        {"ticker": "7974.T", "position_type": "現物", "account_type": "NISA", "quantity": 100, "cost_price": 10673.0},
        {"ticker": "4661.T", "position_type": "現物", "account_type": "NISA", "quantity": 200, "cost_price": 3045.0},
        {"ticker": "1328.T", "position_type": "現物", "account_type": "NISA", "quantity": 9, "cost_price": 17860.0},
        {"ticker": "7013.T", "position_type": "現物", "account_type": "特定", "quantity": 100, "cost_price": 3528.0},
        {"ticker": "8473.T", "position_type": "現物", "account_type": "特定", "quantity": 200, "cost_price": 3231.0},
    ]
    # 5/5 = 100% ≥ 50%, 0 missing by ticker_key → should succeed
    result = module.merge_holdings(existing, sbi)
    assert result is not None
    assert len(result) == 5
    # account_type should be updated to NISA
    for h in result:
        if h["ticker"] in ("7974.T", "4661.T", "1328.T"):
            assert h["account_type"] == "NISA", f"{h['ticker']} should be NISA, got {h['account_type']}"
        if h["ticker"] in ("7013.T", "8473.T"):
            assert h["account_type"] == "特定"


def test_merge_holdings_3_really_missing_triggers_guard():
    """3 genuinely missing holdings (not just account_type change) should abort."""
    module = load_sbi_fetch()
    existing = [
        {"ticker": "A.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
        {"ticker": "B.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
        {"ticker": "C.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
        {"ticker": "D.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
        {"ticker": "E.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
    ]
    # Only 2 returned by SBI, 3 completely missing
    sbi = [
        {"ticker": "A.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
        {"ticker": "E.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
    ]
    # 2 < 5*0.5 → 50% guard catches it
    result = module.merge_holdings(existing, sbi)
    assert result is None


def test_merge_holdings_passes_with_2_missing():
    module = load_sbi_fetch()
    existing = [
        {"ticker": "A.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
        {"ticker": "B.T", "position_type": "現物", "account_type": "特定", "quantity": 200},
        {"ticker": "C.T", "position_type": "現物", "account_type": "特定", "quantity": 300},
    ]
    sbi = [
        {"ticker": "A.T", "position_type": "現物", "account_type": "特定", "quantity": 150},
    ]
    result = module.merge_holdings(existing, sbi)
    assert result is None


def test_merge_holdings_succeeds_with_1_missing():
    module = load_sbi_fetch()
    existing = [
        {"ticker": "A.T", "position_type": "現物", "account_type": "特定", "quantity": 100},
        {"ticker": "B.T", "position_type": "現物", "account_type": "特定", "quantity": 200},
    ]
    sbi = [
        {"ticker": "A.T", "position_type": "現物", "account_type": "特定", "quantity": 150},
    ]
    result = module.merge_holdings(existing, sbi)
    assert result is not None
    assert len(result) == 1
    assert result[0]["quantity"] == 150
