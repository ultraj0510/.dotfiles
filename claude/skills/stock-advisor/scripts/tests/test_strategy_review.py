from strategy_review import classify_strategy_posture, summarize_strategy_review


def test_classify_strategy_posture_uses_validated_strategy():
    posture = classify_strategy_posture({
        "strategy_selection": {
            "selected_strategy": "trend",
            "tradeable": True,
            "reason": "strategy_passed_tradeability_gate",
        },
        "benchmark_comparison": {
            "beats_benchmark_return": True,
            "beats_benchmark_sharpe": True,
            "trade_count": 18,
            "reason": "strategy_beats_benchmark",
        },
        "walk_forward": {
            "consensus": {
                "verdict": "stable",
                "data_quality": "sufficient_oos_trades",
            },
        },
    })

    assert posture["posture"] == "validated_strategy"
    assert posture["automation_allowed"] is True
    assert posture["size_multiplier"] == 1.0


def test_classify_strategy_posture_uses_candidate_strategy_for_positive_but_unvalidated_edge():
    posture = classify_strategy_posture({
        "strategy_selection": {
            "selected_strategy": "hold_baseline",
            "tradeable": False,
            "reason": "no_strategy_passed_tradeability_gate",
        },
        "benchmark_comparison": {
            "beats_benchmark_return": True,
            "beats_benchmark_sharpe": True,
            "trade_count": 18,
            "reason": "strategy_beats_benchmark",
        },
        "baseline": {"wins": 7, "losses": 11, "avg_win_pct": 14.49, "avg_loss_pct": -4.96},
        "walk_forward": {
            "consensus": {
                "verdict": "unstable",
                "data_quality": "thin_oos_trades",
                "total_test_trades": 7,
            },
        },
    })

    assert posture["posture"] == "candidate_strategy"
    # Default mode is "balanced" — candidate strategy has size_multiplier=0.33
    assert posture["automation_allowed"] is True
    assert posture["size_multiplier"] == 0.33
    assert posture["reason"] == "positive_edge_unvalidated"

    # Balanced mode allows reduced-size candidate trades
    posture_balanced = classify_strategy_posture({
        "strategy_selection": {"selected_strategy": "hold_baseline", "tradeable": False, "reason": "no_strategy_passed_tradeability_gate"},
        "baseline": {"wins": 7, "losses": 11, "avg_win_pct": 14.49, "avg_loss_pct": -4.96},
        "benchmark_comparison": {"beats_benchmark_return": True, "beats_benchmark_sharpe": True, "trade_count": 18, "reason": "strategy_beats_benchmark"},
        "walk_forward": {"consensus": {"verdict": "unstable", "data_quality": "thin_oos_trades", "total_test_trades": 7}},
    }, risk_mode="balanced")
    assert posture_balanced["automation_allowed"] is True
    assert posture_balanced["size_multiplier"] == 0.33

    posture = classify_strategy_posture({
        "strategy_selection": {
            "selected_strategy": "hold_baseline",
            "tradeable": False,
            "reason": "no_strategy_passed_tradeability_gate",
        },
        "benchmark_comparison": {
            "beats_benchmark_return": False,
            "beats_benchmark_sharpe": False,
            "trade_count": 13,
            "reason": "strategy_underperforms_benchmark",
        },
    })

    assert posture["posture"] == "hold_baseline"
    assert posture["automation_allowed"] is False
    assert posture["size_multiplier"] == 0.0


def test_summarize_strategy_review_counts_candidate_strategy():
    summary = summarize_strategy_review({
        "7974.T": {
            "strategy_selection": {"tradeable": False},
            "baseline": {"wins": 7, "losses": 11, "avg_win_pct": 14.49, "avg_loss_pct": -4.96},
            "benchmark_comparison": {
                "beats_benchmark_return": True,
                "beats_benchmark_sharpe": True,
                "trade_count": 18,
                "reason": "strategy_beats_benchmark",
            },
            "walk_forward": {
                "consensus": {
                    "verdict": "unstable",
                    "data_quality": "thin_oos_trades",
                    "total_test_trades": 7,
                },
            },
        },
        "1515.T": {
            "strategy_selection": {"tradeable": False},
            "benchmark_comparison": {
                "beats_benchmark_return": False,
                "beats_benchmark_sharpe": False,
                "trade_count": 11,
                "reason": "strategy_underperforms_benchmark",
            },
        },
    })

    assert summary["candidate_strategy"] == 1
    assert summary["hold_baseline"] == 1
    assert summary["validated_strategy"] == 0


def test_profit_protection_is_not_treated_as_hold_baseline_failure():
    posture = classify_strategy_posture({
        "risk_posture": "protect_profit",
        "strategy_selection": {"tradeable": False},
        "benchmark_comparison": {
            "beats_benchmark_return": False,
            "beats_benchmark_sharpe": False,
            "trade_count": 7,
            "reason": "strategy_underperforms_benchmark",
        },
    }, risk_mode="balanced")

    assert posture["posture"] == "profit_protection"
    assert posture["automation_allowed"] is False
    assert posture["size_multiplier"] == 0.0
    assert posture["reason"] == "let_winner_run_with_stop"


def test_manual_range_plan_never_allows_automation():
    posture = classify_strategy_posture({
        "strategy_selection": {"tradeable": False},
        "benchmark_comparison": {
            "beats_benchmark_return": True,
            "beats_benchmark_sharpe": True,
            "trade_count": 18,
            "reason": "strategy_beats_benchmark",
        },
        "baseline": {"wins": 7, "losses": 11, "avg_win_pct": 14.49, "avg_loss_pct": -4.96},
        "walk_forward": {
            "consensus": {
                "verdict": "unstable",
                "data_quality": "thin_oos_trades",
                "total_test_trades": 7,
            },
        },
    }, risk_mode="defensive")

    assert posture["posture"] == "candidate_strategy"
    assert posture["automation_allowed"] is False


def test_candidate_strategy_is_rejected_when_expected_value_is_negative():
    posture = classify_strategy_posture({
        "strategy_selection": {"tradeable": False},
        "baseline": {"wins": 4, "losses": 8, "avg_win_pct": 2.0, "avg_loss_pct": -5.0},
        "benchmark_comparison": {
            "beats_benchmark_return": True,
            "beats_benchmark_sharpe": True,
            "trade_count": 18,
            "reason": "strategy_beats_benchmark",
        },
        "walk_forward": {
            "consensus": {
                "verdict": "unstable",
                "data_quality": "thin_oos_trades",
                "total_test_trades": 7,
            },
        },
    }, risk_mode="balanced")

    assert posture["posture"] == "hold_baseline"
    assert posture["reason"] == "candidate_negative_expected_value"
