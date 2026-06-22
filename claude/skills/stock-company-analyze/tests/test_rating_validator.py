import pytest
from rating_validator import validate_and_correct, EXPECTED_RETURN_BUY_THRESHOLD, EXPECTED_RETURN_SELL_THRESHOLD

def _pm(eps_bull=600, per_bull=12, prob_bull=0.30, eps_base=450, per_base=10, prob_base=0.50, eps_bear=300, per_bear=8, prob_bear=0.20, proposed="BUY"):
    return {
        "proposed_rating": proposed,
        "investment_thesis_ja": "test",
        "scenarios": [
            {"label": "bull", "eps": eps_bull, "per": per_bull, "probability": prob_bull, "rationale_ja": "強気"},
            {"label": "base", "eps": eps_base, "per": per_base, "probability": prob_base, "rationale_ja": "基本"},
            {"label": "bear", "eps": eps_bear, "per": per_bear, "probability": prob_bear, "rationale_ja": "弱気"},
        ],
        "catalysts": [], "disconfirmers": [], "data_gaps": [],
    }

def test_buy_above_20pct():
    r = validate_and_correct(_pm(), 3000, {"coverage_complete": True}, {})
    assert r.final_rating == "BUY"
    assert r.expected_return > 0.20

def test_sell_below_minus_20pct():
    r = validate_and_correct(_pm(eps_bull=150, per_bull=10, prob_bull=0.30, eps_base=120, per_base=10, prob_base=0.50, eps_bear=80, per_bear=8, prob_bear=0.20, proposed="SELL"), 3000, {"coverage_complete": True}, {})
    assert r.final_rating == "SELL"

def test_hold_between():
    r = validate_and_correct(_pm(eps_bull=350, per_bull=10, prob_bull=0.30, eps_base=300, per_base=10, prob_base=0.50, eps_bear=250, per_bear=10, prob_bear=0.20), 3000, {"coverage_complete": True}, {})
    assert r.final_rating == "HOLD"

def test_not_rated_no_price():
    r = validate_and_correct(_pm(), None, {"coverage_complete": True}, {})
    assert r.final_rating == "NOT_RATED"

def test_provisional_when_coverage_incomplete():
    r = validate_and_correct(_pm(), 3000, {"coverage_complete": False}, {})
    assert r.provisional is True

def test_expected_return_formula():
    r = validate_and_correct(_pm(), 3000, {"coverage_complete": True}, {})
    assert abs(r.expected_return - 0.63) < 0.01

def test_short_demoted_when_gates_missing():
    pm = _pm(eps_bull=150, per_bull=10, prob_bull=0.30, eps_base=120, per_base=10, prob_base=0.50, eps_bear=80, per_bear=8, prob_bear=0.20, proposed="SHORT")
    r = validate_and_correct(pm, 3000, {"coverage_complete": True}, {"borrow_rate_available": False})
    assert r.final_rating == "SELL"
    assert r.short_eligible is False
