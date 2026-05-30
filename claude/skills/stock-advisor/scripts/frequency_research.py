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
    years = _period_years(backtest)
    trades_per_year = round(trade_count / years, 2) if years > 0 else 0.0

    if trade_count < 20 or total_test_trades < 8:
        bucket = "sparse"
    elif trade_count < 40 or total_test_trades < 12:
        bucket = "moderate"
    else:
        bucket = "sufficient"

    return {
        "trade_count": trade_count,
        "total_test_trades": total_test_trades,
        "trades_per_year": trades_per_year,
        "frequency_bucket": bucket,
        "needs_frequency_research": bucket in {"sparse", "moderate"},
    }


def summarize_frequency_diagnostics(backtests: dict) -> dict:
    summary = {"sparse": 0, "moderate": 0, "sufficient": 0}
    for backtest in backtests.values():
        bucket = classify_trade_frequency(backtest)["frequency_bucket"]
        summary[bucket] += 1
    return summary
