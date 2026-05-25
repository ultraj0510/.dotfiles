"""Unit tests for trade_advisor.py"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trade_advisor import (
    map_score_to_opinion, compute_pnl_contribution, compute_trend_alignment,
    compute_confidence, compute_advisory, compute_target_prices,
    assess_risk, OPINION_THRESHOLDS,
)


def test_score_to_opinion_mapping():
    """Boundary values for score-to-opinion mapping."""
    assert map_score_to_opinion(70) == ("STRONG_BUY", "買い増し推奨")
    assert map_score_to_opinion(60) == ("STRONG_BUY", "買い増し推奨")
    assert map_score_to_opinion(59) == ("BUY_MORE", "押し目買い検討")
    assert map_score_to_opinion(30) == ("BUY_MORE", "押し目買い検討")
    assert map_score_to_opinion(29) == ("HOLD", "現状維持")
    assert map_score_to_opinion(-10) == ("HOLD", "現状維持")
    assert map_score_to_opinion(-11) == ("REDUCE", "リバウンド時に一部売却")
    assert map_score_to_opinion(-40) == ("REDUCE", "リバウンド時に一部売却")
    assert map_score_to_opinion(-41) == ("SELL", "全株売却")
    assert map_score_to_opinion(-100) == ("SELL", "全株売却")


def test_pnl_contribution():
    """P&L contribution with threshold and cap."""
    assert compute_pnl_contribution(12) == 20
    assert compute_pnl_contribution(3) == 0
    assert compute_pnl_contribution(-12) == -20
    assert compute_pnl_contribution(35) == 30


def test_trend_alignment():
    """Trend alignment with strength weighting."""
    assert compute_trend_alignment(5.0, "weak_uptrend") == 12.5
    assert compute_trend_alignment(-5.0, "strong_downtrend") == -25.0
    assert compute_trend_alignment(5.0, "ranging") == 0.0


def test_advisory_output_schema():
    """compute_advisory returns expected structure with all required keys."""
    result = compute_advisory(
        {"score": 50},
        "strong_uptrend",
        10.0,
        {"active_signals": [
            {"rule": "test_rule", "historical_win_rate": 60.0, "trade_count": 10},
        ]},
    )
    assert "opinion" in result
    assert "opinion_ja" in result
    assert "confidence" in result
    assert "score_breakdown" in result
    breakdown = result["score_breakdown"]
    assert "overall_score_contribution" in breakdown
    assert "historical_win_rate_contribution" in breakdown
    assert "trend_alignment_contribution" in breakdown
    assert "pnl_contribution" in breakdown
    assert "total" in breakdown
    assert "reasoning" in result
    assert len(OPINION_THRESHOLDS) == 4


def test_risk_assessment_spot_vs_margin():
    """Spot mode has no margin factor; margin mode includes it."""
    common = dict(
        market_price=3000,
        shares=100,
        portfolio_value=0,
        indicators={},
        signals=[],
        atr_value=0,
    )
    spot_result = assess_risk(**common, mode="spot")
    margin_result = assess_risk(**common, mode="margin")

    factor_names = [f["name"] for f in spot_result["factors"]]
    assert "margin" not in factor_names

    factor_names = [f["name"] for f in margin_result["factors"]]
    assert "margin" in factor_names
