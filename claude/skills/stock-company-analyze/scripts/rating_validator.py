"""Deterministic rating validation and correction. No LLM involved."""
from dataclasses import dataclass, field

EXPECTED_RETURN_BUY_THRESHOLD = 0.20
EXPECTED_RETURN_SELL_THRESHOLD = -0.20


@dataclass
class RatingResult:
    final_rating: str
    pm_proposal: str
    adjusted: bool = False
    adjustment_reasons: list[str] = field(default_factory=list)
    provisional: bool = False
    provisional_reasons: list[str] = field(default_factory=list)
    short_eligible: bool = False
    expected_price: float | None = None
    expected_return: float | None = None
    scenario_prices: dict[str, float] = field(default_factory=dict)


def validate_and_correct(pm_output, current_price, data_quality, short_data):
    reasons = []
    provisional_reasons = []

    if current_price is None or current_price <= 0:
        return RatingResult(
            final_rating="NOT_RATED", pm_proposal=pm_output.get("proposed_rating", ""),
            adjusted=True, adjustment_reasons=["現在株価がないためNOT_RATED"],
            provisional=True, provisional_reasons=["価格データ不足"],
        )

    scenarios = pm_output.get("scenarios", [])
    if len(scenarios) != 3:
        return RatingResult(
            final_rating="NOT_RATED", pm_proposal=pm_output.get("proposed_rating", ""),
            adjusted=True, adjustment_reasons=["シナリオが3つないためNOT_RATED"],
            provisional=True, provisional_reasons=["シナリオ数不正"],
        )

    scenario_prices = {}
    expected_price = 0.0
    for s in scenarios:
        price = s["eps"] * s["per"]
        scenario_prices[s["label"]] = price
        expected_price += price * s["probability"]

    expected_return = expected_price / current_price - 1

    if expected_return >= EXPECTED_RETURN_BUY_THRESHOLD:
        computed_rating = "BUY"
    elif expected_return > EXPECTED_RETURN_SELL_THRESHOLD:
        computed_rating = "HOLD"
    else:
        computed_rating = "SELL"

    pm_rating = pm_output.get("proposed_rating", computed_rating)
    adjusted = False
    if pm_rating != computed_rating:
        adjusted = True
        reasons.append(f"PM原案{pm_rating}→期待リターン{expected_return:.1%}により{computed_rating}へ補正")

    final_rating = computed_rating
    short_eligible = False

    if final_rating == "SELL" and pm_rating in ("SELL", "SHORT"):
        gates = [
            ("借株料確認", short_data.get("borrow_rate_available")),
            ("空売り残高確認", short_data.get("short_interest_available")),
            ("踏み上げリスク確認", short_data.get("squeeze_risk_checked")),
            ("下落カタリスト明確", short_data.get("clear_downside_catalyst")),
        ]
        if all(passed for _, passed in gates):
            final_rating = "SHORT"
            short_eligible = True
        elif pm_rating == "SHORT":
            adjusted = True
            missing = [name for name, passed in gates if not passed]
            reasons.append(f"SHORT条件不足({', '.join(missing)})のためSELLを維持")

    if not data_quality.get("coverage_complete", False):
        provisional_reasons.append("IRカバレッジ不完全")

    return RatingResult(
        final_rating=final_rating, pm_proposal=pm_rating,
        adjusted=adjusted, adjustment_reasons=reasons,
        provisional=len(provisional_reasons) > 0, provisional_reasons=provisional_reasons,
        short_eligible=short_eligible,
        expected_price=round(expected_price, 2),
        expected_return=round(expected_return, 4),
        scenario_prices={k: round(v, 2) for k, v in scenario_prices.items()},
    )
