import pytest
from integrated_judgment import compute_integrated_judgment

MATRIX_CASES = [
    ("BUY",  "BUY",  "BUY",  "ACT_NOW"),
    ("BUY",  "HOLD", "BUY",  "WAIT"),
    ("BUY",  "SELL", "BUY",  "WAIT"),
    ("HOLD", "BUY",  "HOLD", "NO_TRADE"),
    ("HOLD", "HOLD", "HOLD", "NO_TRADE"),
    ("HOLD", "SELL", "HOLD", "NO_TRADE"),
    ("SELL", "BUY",  "SELL", "WAIT"),
    ("SELL", "HOLD", "SELL", "WAIT"),
    ("SELL", "SELL", "SELL", "ACT_NOW"),
]

@pytest.mark.parametrize("fund,tech,exp_rating,exp_posture", MATRIX_CASES)
def test_conflict_matrix(fund, tech, exp_rating, exp_posture):
    result = compute_integrated_judgment(fund, tech)
    assert result["investment_rating"] == exp_rating
    assert result["execution_posture"] == exp_posture

def test_execution_posture_never_reduce():
    for fund in ("BUY", "HOLD", "SELL"):
        for tech in ("BUY", "HOLD", "SELL"):
            result = compute_integrated_judgment(fund, tech)
            assert result["execution_posture"] in ("ACT_NOW", "WAIT", "NO_TRADE")

def test_investment_rating_never_reduce():
    for fund in ("BUY", "HOLD", "SELL"):
        for tech in ("BUY", "HOLD", "SELL"):
            result = compute_integrated_judgment(fund, tech)
            assert result["investment_rating"] in ("BUY", "HOLD", "SELL")

def test_reasoning_is_non_empty():
    result = compute_integrated_judgment("HOLD", "BUY")
    assert len(result["reasoning"]) > 0

def test_invalid_fundamental_rating_defaults_to_hold():
    result = compute_integrated_judgment("INVALID", "BUY")
    assert result["investment_rating"] == "HOLD"

def test_invalid_technical_direction_defaults_to_hold():
    result = compute_integrated_judgment("BUY", "INVALID")
    assert result["investment_rating"] == "BUY"
    assert result["execution_posture"] == "WAIT"

def test_both_invalid_defaults_to_hold():
    result = compute_integrated_judgment("INVALID", "INVALID")
    assert result["investment_rating"] == "HOLD"
    assert result["execution_posture"] == "NO_TRADE"
