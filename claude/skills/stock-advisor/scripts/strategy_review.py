"""Strategy review: classify strategy posture and risk-mode sizing after gate evaluation."""


RISK_MODE_MULTIPLIERS = {
    "defensive": {
        "validated_strategy": 1.0,
        "candidate_strategy": 0.0,
        "hold_baseline": 0.0,
        "profit_protection": 0.0,
    },
    "balanced": {
        "validated_strategy": 1.0,
        "candidate_strategy": 0.33,
        "hold_baseline": 0.0,
        "profit_protection": 0.0,
    },
    "aggressive": {
        "validated_strategy": 1.0,
        "candidate_strategy": 0.50,
        "hold_baseline": 0.0,
        "profit_protection": 0.0,
    },
}


def _walk_forward_consensus(backtest: dict) -> dict:
    return backtest.get("walk_forward", {}).get("consensus", {})


def _is_candidate_strategy(backtest: dict) -> bool:
    comparison = backtest.get("benchmark_comparison", {})
    consensus = _walk_forward_consensus(backtest)
    trade_count = int(comparison.get("trade_count", 0) or 0)
    total_test_trades = int(consensus.get("total_test_trades", 0) or 0)
    verdict = consensus.get("verdict")
    ev = backtest.get("expected_value_after_cost_pct")

    if ev is not None and ev < 0:
        return False
    if not comparison.get("beats_benchmark_return"):
        return False
    if not comparison.get("beats_benchmark_sharpe"):
        return False
    if trade_count < 6:
        return False
    if total_test_trades < 3:
        return False
    if verdict in {"no_trades", "insufficient_data"}:
        return False
    return True


def classify_strategy_posture(backtest: dict, risk_mode: str = "balanced") -> dict:
    if backtest.get("risk_posture") == "protect_profit":
        return {
            "posture": "profit_protection",
            "automation_allowed": False,
            "size_multiplier": 0.0,
            "reason": "let_winner_run_with_stop",
        }

    selection = backtest.get("strategy_selection", {})
    comparison = backtest.get("benchmark_comparison", {})
    risk_policy = RISK_MODE_MULTIPLIERS.get(risk_mode, RISK_MODE_MULTIPLIERS["defensive"])

    if selection.get("tradeable"):
        posture = "validated_strategy"
        reason = selection.get("reason", "strategy_tradeable")
    elif _is_candidate_strategy(backtest):
        posture = "candidate_strategy"
        reason = "positive_edge_unvalidated"
    else:
        posture = "hold_baseline"
        ev = backtest.get("expected_value_after_cost_pct")
        if ev is not None and ev < 0:
            reason = "candidate_negative_expected_value"
        else:
            reason = comparison.get("reason", selection.get("reason", "strategy_not_tradeable"))

    size_multiplier = risk_policy[posture]
    return {
        "posture": posture,
        "automation_allowed": size_multiplier > 0,
        "size_multiplier": size_multiplier,
        "reason": reason,
    }


def summarize_strategy_review(backtests: dict, risk_mode: str = "balanced") -> dict:
    summary = {
        "validated_strategy": 0,
        "candidate_strategy": 0,
        "hold_baseline": 0,
        "profit_protection": 0,
        "automation_allowed": 0,
        "risk_mode": risk_mode,
    }
    for backtest in backtests.values():
        posture = classify_strategy_posture(backtest, risk_mode=risk_mode)
        summary[posture["posture"]] += 1
        if posture["automation_allowed"]:
            summary["automation_allowed"] += 1
    return summary
