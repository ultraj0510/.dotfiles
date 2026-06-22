import pytest
from confidence import compute_confidence

def test_full_confidence_high():
    r = compute_confidence(
        {"coverage_complete": True, "essential_items_available": 10},
        {"price_age_days": 0, "news_age_hours": 2, "ir_age_days": 3},
        {"constraints_met": True, "spread": 0.30},
        {"all_claims_have_evidence": True, "unresolved_contradictions": False},
        provisional=False, not_rated=False,
    )
    assert r["score"] >= 80
    assert r["level"] == "High"

def test_low_confidence_stale():
    r = compute_confidence(
        {"coverage_complete": False, "essential_items_available": 3},
        {"price_age_days": 10, "news_age_hours": 200, "ir_age_days": 100},
        {"constraints_met": False, "spread": 2.0},
        {"all_claims_have_evidence": False, "unresolved_contradictions": True},
        provisional=True, not_rated=False,
    )
    assert r["score"] < 50
    assert r["level"] == "Low"

def test_not_rated_forces_low():
    r = compute_confidence(
        {"coverage_complete": True, "essential_items_available": 10},
        {"price_age_days": 0, "news_age_hours": 1, "ir_age_days": 3},
        {"constraints_met": True, "spread": 0.20},
        {"all_claims_have_evidence": True, "unresolved_contradictions": False},
        provisional=False, not_rated=True,
    )
    assert r["level"] == "Low"

def test_provisional_cannot_be_high():
    r = compute_confidence(
        {"coverage_complete": True, "essential_items_available": 10},
        {"price_age_days": 0, "news_age_hours": 1, "ir_age_days": 3},
        {"constraints_met": True, "spread": 0.20},
        {"all_claims_have_evidence": True, "unresolved_contradictions": False},
        provisional=True, not_rated=False,
    )
    assert r["level"] != "High"
