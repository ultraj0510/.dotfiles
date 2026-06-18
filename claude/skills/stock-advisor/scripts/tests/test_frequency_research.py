from frequency_research import classify_trade_frequency, summarize_frequency_diagnostics


def test_classify_trade_frequency_marks_sparse_strategy():
    result = classify_trade_frequency({
        "baseline": {"trade_count": 7},
        "walk_forward": {"consensus": {"total_test_trades": 3}},
        "period": {"years": 5},
    })

    assert result["frequency_bucket"] == "sparse"
    assert result["trades_per_year"] == 1.4
    assert result["needs_frequency_research"] is True


def test_classify_trade_frequency_marks_sufficient_strategy():
    result = classify_trade_frequency({
        "baseline": {"trade_count": 45},
        "walk_forward": {"consensus": {"total_test_trades": 16}},
        "period": {"years": 5},
    })

    assert result["frequency_bucket"] == "sufficient"
    assert result["needs_frequency_research"] is False


def test_summarize_frequency_diagnostics_counts_sparse_tickers():
    summary = summarize_frequency_diagnostics({
        "285A.T": {"baseline": {"trade_count": 7}, "walk_forward": {"consensus": {"total_test_trades": 3, "valid_test_windows": 2, "overfit_count": 1, "data_quality": "thin_oos_trades"}}, "period": {"years": 5}},
        "7974.T": {"baseline": {"trade_count": 45}, "walk_forward": {"consensus": {"total_test_trades": 16, "valid_test_windows": 5, "overfit_count": 0, "data_quality": "sufficient_oos_trades"}}, "period": {"years": 5}},
    })

    assert summary["summary"]["sparse"] == 1
    assert summary["summary"]["sufficient"] == 1
    assert "285A.T" in summary["tickers"]
    assert summary["tickers"]["285A.T"]["diagnosis"]
