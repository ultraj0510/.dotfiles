from strategy_review import classify_strategy_posture, summarize_strategy_review


def test_classify_strategy_posture_uses_validated_trade_strategy():
    posture = classify_strategy_posture({
        "strategy_selection": {
            "selected_strategy": "trend",
            "tradeable": True,
            "reason": "strategy_passed_tradeability_gate",
        },
        "benchmark_comparison": {
            "beats_benchmark_return": True,
            "beats_benchmark_sharpe": True,
            "reason": "strategy_beats_benchmark",
        },
    })
    assert posture["posture"] == "validated_trade_strategy"
    assert posture["automation_allowed"] is True


def test_classify_strategy_posture_keeps_manual_range_plan_for_quality_rejection():
    posture = classify_strategy_posture({
        "strategy_selection": {
            "selected_strategy": "hold_baseline",
            "tradeable": False,
            "reason": "no_strategy_passed_tradeability_gate",
        },
        "benchmark_comparison": {
            "beats_benchmark_return": True,
            "beats_benchmark_sharpe": True,
            "reason": "too_few_strategy_trades",
        },
    })
    assert posture["posture"] == "manual_range_plan"
    assert posture["automation_allowed"] is False


def test_classify_strategy_posture_uses_hold_baseline_for_underperformer():
    posture = classify_strategy_posture({
        "strategy_selection": {
            "selected_strategy": "hold_baseline",
            "tradeable": False,
            "reason": "no_strategy_passed_tradeability_gate",
        },
        "benchmark_comparison": {
            "beats_benchmark_return": False,
            "beats_benchmark_sharpe": False,
            "reason": "strategy_underperforms_benchmark",
        },
    })
    assert posture["posture"] == "hold_baseline"
    assert posture["automation_allowed"] is False


def test_summarize_strategy_review_counts_postures():
    summary = summarize_strategy_review({
        "7974.T": {
            "strategy_selection": {"tradeable": False},
            "benchmark_comparison": {
                "beats_benchmark_return": True,
                "beats_benchmark_sharpe": True,
                "reason": "too_few_strategy_trades",
            },
        },
        "1515.T": {
            "strategy_selection": {"tradeable": False},
            "benchmark_comparison": {
                "beats_benchmark_return": False,
                "beats_benchmark_sharpe": False,
                "reason": "strategy_underperforms_benchmark",
            },
        },
    })
    assert summary["manual_range_plan"] == 1
    assert summary["hold_baseline"] == 1
    assert summary["validated_trade_strategy"] == 0


def test_manual_range_plan_never_allows_automation():
    posture = classify_strategy_posture({
        "strategy_selection": {"tradeable": False},
        "benchmark_comparison": {
            "beats_benchmark_return": True,
            "beats_benchmark_sharpe": True,
            "reason": "too_few_strategy_trades",
        },
    })
    assert posture["posture"] == "manual_range_plan"
    assert posture["automation_allowed"] is False
