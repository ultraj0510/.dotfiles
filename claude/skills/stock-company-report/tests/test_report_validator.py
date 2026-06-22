import pytest
from report_validator import validate_for_report, extract_sections

def _minimal():
    return {
        "schema_version": "1.0", "run_id": "r1", "ticker": "285A",
        "company_name": "キオクシア", "as_of": "2026-06-22T15:15:32+09:00",
        "status": "completed",
        "rating": {"final": "HOLD", "adjusted": False, "provisional": False, "short_eligible": False,
                    "portfolio_manager_proposal": "HOLD", "adjustment_reasons": [], "provisional_reasons": []},
        "expected_return": {"current_price": 1000, "expected_price": 1100, "expected_return": 0.10, "scenario_prices": {}},
        "confidence": {"score": 80, "level": "High", "components": {}},
        "scenarios": [], "catalysts": [], "disconfirmers": [], "unknowns": [],
        "analyst_reports": {}, "debate": {}, "evidence_pack_sha256": "a" * 64,
    }

def test_validate_accepts_minimal():
    assert validate_for_report(_minimal()) == []

def test_validate_rejects_missing_rating():
    a = _minimal(); del a["rating"]
    assert len(validate_for_report(a)) > 0

def test_validate_rejects_wrong_schema():
    a = _minimal(); a["schema_version"] = "99.0"
    assert len(validate_for_report(a)) > 0

def test_extract_sections_returns_fields():
    s = extract_sections(_minimal())
    assert s.ticker == "285A"
    assert s.final_rating == "HOLD"
    assert s.current_price == 1000
