"""Frequency diagnostics: classify trade frequency and summarize across tickers."""


def _period_years(backtest: dict) -> float:
    years = backtest.get("period", {}).get("years")
    if years:
        return float(years)
    return 5.0


def classify_trade_frequency(backtest: dict) -> dict:
    trade_count = int(backtest.get("baseline", {}).get("trade_count", 0) or 0)
    consensus = backtest.get("walk_forward", {}).get("consensus", {})
    total_test_trades = int(consensus.get("total_test_trades", 0) or 0)
    valid_test_windows = int(consensus.get("valid_test_windows", 0) or 0)
    overfit_count = int(consensus.get("overfit_count", 0) or 0)
    data_quality = consensus.get("data_quality", "")
    stability_flag = consensus.get("stability_flag", "")
    years = _period_years(backtest)
    trades_per_year = round(trade_count / years, 2) if years > 0 else 0.0

    if trade_count < 20 or total_test_trades < 8:
        bucket = "sparse"
    elif trade_count < 40 or total_test_trades < 12:
        bucket = "moderate"
    else:
        bucket = "sufficient"

    # Build diagnosis
    reasons = []
    if total_test_trades == 0:
        reasons.append("no_oos_trades")
    elif total_test_trades < 15:
        reasons.append("oos_too_thin")
    if valid_test_windows < 3:
        reasons.append("window_coverage_too_low")
    if overfit_count > 0 and valid_test_windows > 0 and overfit_count > valid_test_windows / 2:
        reasons.append("overfit_majority")
    if trade_count < 20:
        reasons.append("low_full_period_frequency")

    diagnosis_map = {
        "no_oos_trades": "OOS取引が0件",
        "oos_too_thin": f"OOS取引{total_test_trades}件と不足",
        "window_coverage_too_low": f"有効OOS窓{valid_test_windows}と不足",
        "overfit_majority": f"過学習窓{overfit_count}/{valid_test_windows}",
        "low_full_period_frequency": f"5年取引{trade_count}件と低頻度",
    }
    diagnosis = "; ".join(diagnosis_map.get(r, r) for r in reasons) if reasons else "十分な取引数とOOS証拠あり"

    return {
        "trade_count": trade_count,
        "total_test_trades": total_test_trades,
        "valid_test_windows": valid_test_windows,
        "overfit_count": overfit_count,
        "data_quality": data_quality,
        "stability_flag": stability_flag,
        "trades_per_year": trades_per_year,
        "frequency_bucket": bucket,
        "needs_frequency_research": bucket in {"sparse", "moderate"},
        "diagnosis": diagnosis,
    }


def summarize_frequency_diagnostics(backtests: dict) -> dict:
    summary = {"sparse": 0, "moderate": 0, "sufficient": 0, "thin_oos_trades": 0, "unstable": 0, "limited": 0}
    tickers = {}
    for ticker, backtest in backtests.items():
        diag = classify_trade_frequency(backtest)
        summary[diag["frequency_bucket"]] += 1
        if diag["data_quality"] == "thin_oos_trades":
            summary["thin_oos_trades"] += 1
        wf = backtest.get("walk_forward", {})
        verdict = wf.get("verdict") or wf.get("consensus", {}).get("verdict", "")
        if verdict == "unstable":
            summary["unstable"] += 1
        elif verdict == "limited":
            summary["limited"] += 1
        tickers[ticker] = diag
    return {"summary": summary, "tickers": tickers}
