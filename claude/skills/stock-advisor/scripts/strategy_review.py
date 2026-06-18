"""Strategy review: classify strategy posture and risk-mode sizing after gate evaluation."""

from signal_reliability import expected_value_after_cost_pct, shrink_win_probability


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


def candidate_expected_value(candidate: dict) -> float | None:
    baseline = candidate.get("baseline", {})
    trade_count = int(baseline.get("trade_count", 0) or 0)
    wins_raw = baseline.get("wins")
    losses_raw = baseline.get("losses")
    if wins_raw is not None and losses_raw is not None:
        wins = int(wins_raw or 0)
        losses = int(losses_raw or 0)
    else:
        win_rate = baseline.get("win_rate")
        if win_rate is None or trade_count <= 0:
            return None
        wins = round(trade_count * float(win_rate) / 100)
        losses = max(trade_count - wins, 0)

    avg_win = float(baseline.get("avg_win_pct", 0) or 0)
    avg_loss = float(baseline.get("avg_loss_pct", 0) or 0)
    if wins + losses == 0 or avg_win == 0 or avg_loss == 0:
        return None
    return expected_value_after_cost_pct(
        p_win=shrink_win_probability(wins, losses),
        avg_win_pct=avg_win,
        avg_loss_pct=avg_loss,
        round_trip_cost_pct=0.5,
    )


def _is_candidate_strategy(backtest: dict) -> bool:
    comparison = backtest.get("benchmark_comparison", {})
    consensus = _walk_forward_consensus(backtest)
    trade_count = int(comparison.get("trade_count", 0) or 0)
    total_test_trades = int(consensus.get("total_test_trades", 0) or 0)
    verdict = consensus.get("verdict")
    ev = candidate_expected_value(backtest)

    if ev is None or ev < 0:
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


def _candidate_input(strategy_name: str, strategy_result: dict) -> dict:
    return {
        "strategy_name": strategy_name,
        "benchmark_comparison": strategy_result.get("benchmark_comparison", {}),
        "walk_forward": strategy_result.get("walk_forward", {}),
        "baseline": strategy_result.get("baseline", {}),
    }


def _candidate_score(candidate: dict) -> tuple:
    comparison = candidate.get("benchmark_comparison", {})
    return (
        float(comparison.get("excess_sharpe", 0) or 0),
        float(comparison.get("excess_total_return", 0) or 0),
        int(comparison.get("trade_count", 0) or 0),
    )


def select_candidate_strategy(backtest: dict) -> dict | None:
    candidates = []
    for strategy_name, strategy_result in backtest.get("strategy_comparison", {}).items():
        candidate = _candidate_input(strategy_name, strategy_result)
        if _is_candidate_strategy(candidate):
            comparison = candidate["benchmark_comparison"]
            ev = candidate_expected_value(candidate)
            candidates.append({
                "strategy": strategy_name,
                "reason": "positive_edge_unvalidated",
                "excess_sharpe": comparison.get("excess_sharpe", 0),
                "excess_total_return": comparison.get("excess_total_return", 0),
                "trade_count": comparison.get("trade_count", 0),
                "expected_value_after_cost_pct": round(ev, 4) if ev is not None else None,
                "wf_verdict": candidate.get("walk_forward", {}).get("consensus", {}).get("verdict"),
                "wf_data_quality": candidate.get("walk_forward", {}).get("consensus", {}).get("data_quality"),
                "_score": _candidate_score(candidate),
            })

    if not candidates:
        return None

    selected = max(candidates, key=lambda c: c["_score"])
    selected.pop("_score", None)
    return selected


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
    candidate = select_candidate_strategy(backtest)

    if selection.get("tradeable"):
        posture = "validated_strategy"
        reason = selection.get("reason", "strategy_tradeable")
        candidate_strategy = selection.get("selected_strategy")
    elif candidate:
        posture = "candidate_strategy"
        reason = candidate["reason"]
        candidate_strategy = candidate["strategy"]
    elif _is_candidate_strategy(backtest):
        posture = "candidate_strategy"
        reason = "positive_edge_unvalidated"
        candidate_strategy = None
    else:
        posture = "hold_baseline"
        candidate_strategy = None
        ev = candidate_expected_value(backtest)
        if ev is not None and ev <= 0 and comparison.get("beats_benchmark_return"):
            reason = "candidate_negative_expected_value"
        else:
            reason = comparison.get("reason", selection.get("reason", "strategy_not_tradeable"))

    size_multiplier = risk_policy[posture]
    result = {
        "posture": posture,
        "automation_allowed": size_multiplier > 0,
        "size_multiplier": size_multiplier,
        "reason": reason,
        "candidate_strategy": candidate_strategy,
    }
    if candidate:
        result["candidate"] = candidate
    return result


def summarize_strategy_review(backtests: dict, risk_mode: str = "balanced") -> dict:
    summary = {
        "validated_strategy": 0,
        "candidate_strategy": 0,
        "hold_baseline": 0,
        "profit_protection": 0,
        "automation_allowed": 0,
        "risk_mode": risk_mode,
        "candidates": {},
    }
    for ticker, backtest in backtests.items():
        posture = classify_strategy_posture(backtest, risk_mode=risk_mode)
        summary[posture["posture"]] += 1
        if posture["automation_allowed"]:
            summary["automation_allowed"] += 1
        if posture["posture"] == "candidate_strategy":
            summary["candidates"][ticker] = posture.get("candidate", {})
    return summary
