import json, pytest
from pathlib import Path
from generate_report import generate_html, generate_report

def _sample():
    return {
        "schema_version": "1.0", "run_id": "r1", "ticker": "285A",
        "company_name": "キオクシアホールディングス", "as_of": "2026-06-22T15:15:32+09:00",
        "status": "completed",
        "rating": {"final": "HOLD", "adjusted": True, "provisional": False, "short_eligible": False,
                    "portfolio_manager_proposal": "BUY", "adjustment_reasons": ["期待リターンがHOLD閾値内"], "provisional_reasons": []},
        "expected_return": {"current_price": 109200, "expected_price": 115000, "expected_return": 0.053, "scenario_prices": {"bull": 180000, "base": 115000, "bear": 70000}},
        "confidence": {"score": 72, "level": "Medium", "components": {"essential_data": 24, "data_freshness": 15, "primary_source_coverage": 10, "scenario_stability": 15, "bull_bear_consistency": 8}},
        "scenarios": [
            {"label": "bull", "eps": 600, "per": 15, "probability": 0.30, "rationale_ja": "AI需要拡大"},
            {"label": "base", "eps": 450, "per": 10, "probability": 0.50, "rationale_ja": "現状維持"},
            {"label": "bear", "eps": 300, "per": 7, "probability": 0.20, "rationale_ja": "NAND価格下落"},
        ],
        "catalysts": ["2026年7月 Q1決算発表"], "disconfirmers": ["NAND価格30%以上下落"],
        "unknowns": ["来期の設備投資計画"], "monitoring_triggers": [],
        "analyst_reports": {}, "debate": {},
        "evidence_pack_sha256": "a" * 64, "run_manifest_ref": "claude-sonnet-4-6",
    }

def test_generate_html_returns_string():
    html = generate_html(_sample())
    assert isinstance(html, str)
    assert "<!doctype html>" in html.lower()
    assert "285A" in html
    assert "キオクシアホールディングス" in html
    assert "HOLD" in html
    assert "109,200" in html

def test_xss_escaping():
    a = _sample(); a["company_name"] = '<script>alert(1)</script>'
    html = generate_html(a)
    assert '<script>alert' not in html
    assert '&lt;script&gt;' in html

def test_generate_report_writes_file(tmp_path):
    ap = tmp_path / "analysis.json"
    ap.write_text(json.dumps(_sample()))
    out = generate_report(ap, tmp_path / "out")
    assert out.exists()
    assert "285A" in out.read_text()

def test_empty_sections_hidden():
    a = _sample(); a["catalysts"] = []; a["disconfirmers"] = []; a["unknowns"] = []
    html = generate_html(a)
    assert "6か月以内のカタリスト" not in html
    assert "反証条件</h2>" not in html

def test_pm_audit_when_adjusted():
    html = generate_html(_sample())
    assert "PM原案" in html
    assert "BUY" in html
