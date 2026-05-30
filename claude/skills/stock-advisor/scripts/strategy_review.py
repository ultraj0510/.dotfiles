"""Strategy review: classify posture and summarize across tickers after the strategy gate is evaluated."""


def classify_strategy_posture(backtest: dict) -> dict:
    selection = backtest.get("strategy_selection", {})
    comparison = backtest.get("benchmark_comparison", {})

    if selection.get("tradeable"):
        return {
            "posture": "validated_trade_strategy",
            "automation_allowed": True,
            "reason": selection.get("reason", "strategy_tradeable"),
        }

    beats_return = bool(comparison.get("beats_benchmark_return"))
    beats_sharpe = bool(comparison.get("beats_benchmark_sharpe"))
    reason = comparison.get("reason", selection.get("reason", "strategy_not_tradeable"))

    if beats_return and beats_sharpe and reason in {"too_few_strategy_trades", "thin_oos_trades", "no_oos_trades"}:
        return {
            "posture": "manual_range_plan",
            "automation_allowed": False,
            "reason": reason,
        }

    return {
        "posture": "hold_baseline",
        "automation_allowed": False,
        "reason": reason,
    }


def summarize_strategy_review(backtests: dict) -> dict:
    summary = {
        "validated_trade_strategy": 0,
        "manual_range_plan": 0,
        "hold_baseline": 0,
    }
    for backtest in backtests.values():
        posture = classify_strategy_posture(backtest)["posture"]
        summary[posture] += 1
    return summary
