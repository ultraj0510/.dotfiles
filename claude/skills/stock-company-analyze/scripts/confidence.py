"""Deterministic confidence score (0-100) per spec."""
def compute_confidence(data_quality, data_freshness, scenario_stability, bull_bear_consistency,
                       provisional, not_rated):
    if not_rated:
        return {"score": 0, "level": "Low", "components": {}}

    essential = data_quality.get("essential_items_available", 0)
    data_score = min(essential * 3, 30)

    price_age = data_freshness.get("price_age_days", 999)
    news_age = data_freshness.get("news_age_hours", 999)
    ir_age = data_freshness.get("ir_age_days", 999)
    if price_age <= 0 and news_age <= 24 and ir_age <= 7:
        freshness_score = 20
    elif price_age <= 1 and news_age <= 72 and ir_age <= 30:
        freshness_score = 15
    elif price_age <= 5 and news_age <= 168 and ir_age <= 90:
        freshness_score = 8
    else:
        freshness_score = 0

    coverage_complete = data_quality.get("coverage_complete", False)
    if coverage_complete:
        coverage_score = 20
    elif data_quality.get("has_latest_earnings_or_strategy", False):
        coverage_score = 10
    else:
        coverage_score = 0

    constraints_met = scenario_stability.get("constraints_met", False)
    spread = scenario_stability.get("spread", 999)
    if constraints_met and spread <= 0.50:
        scenario_score = 15
    elif constraints_met and spread <= 1.00:
        scenario_score = 10
    elif constraints_met:
        scenario_score = 5
    else:
        scenario_score = 0

    all_evidence = bull_bear_consistency.get("all_claims_have_evidence", False)
    contradictions = bull_bear_consistency.get("unresolved_contradictions", False)
    if all_evidence and not contradictions:
        consistency_score = 15
    elif all_evidence:
        consistency_score = 8
    else:
        consistency_score = 0

    total = data_score + freshness_score + coverage_score + scenario_score + consistency_score
    if total >= 80:
        level = "High"
    elif total >= 50:
        level = "Medium"
    else:
        level = "Low"
    if provisional and level == "High":
        level = "Medium"

    return {
        "score": total, "level": level,
        "components": {
            "essential_data": data_score,
            "data_freshness": freshness_score,
            "primary_source_coverage": coverage_score,
            "scenario_stability": scenario_score,
            "bull_bear_consistency": consistency_score,
        },
    }
