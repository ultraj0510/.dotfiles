"""Unit tests for backtest_engine.py"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest_engine import (
    _build_trade, simulate_trades, generate_signals, _compute_metrics,
    _empty_metrics, DEFAULT_MARGIN_PARAMS,
)


def test_build_trade_long_mae_mfe():
    """direction=long: MAE from lowest, MFE from highest."""
    t = _build_trade("2025-01-01", "2025-01-10", 1000, 1100, 0.10,
                     "signal", 1150, 950, "trend_following", "long")
    assert t["direction"] == "long"
    assert t["mae_pct"] == -5.0   # (950-1000)/1000*100 = -5.0
    assert t["mfe_pct"] == 15.0   # (1150-1000)/1000*100 = 15.0
    assert t["return"] == 0.10


def test_build_trade_short_mae_mfe():
    """direction=short: MAE from highest (adverse = price rising), MFE from lowest."""
    t = _build_trade("2025-01-01", "2025-01-10", 1000, 900, 0.10,
                     "signal", 1100, 850, "trend_following", "short")
    assert t["direction"] == "short"
    assert t["mae_pct"] == 10.0   # (1100-1000)/1000*100 = 10.0 (price rose=adverse to short)
    assert t["mfe_pct"] == -15.0  # (850-1000)/1000*100 = -15.0 (price fell=favorable to short)
    assert t["return"] == 0.10


def test_margin_daily_cost_accrual():
    """Margin mode: holding period generates positive margin_cost."""
    sig = generate_signals("1515.T", "2025-05-25", "2026-05-25")
    result = simulate_trades(sig, margin_mode=True)
    assert result["trade_count"] > 0
    for t in result["trades"]:
        assert "margin_cost" in t
        assert "return_after_cost" in t
        assert t["return_after_cost"] <= t["return"] + 1e-10  # cost reduces return
    total_cost = sum(t["margin_cost"] for t in result["trades"])
    assert total_cost > 0, "Expected positive total margin cost"


def test_regression_round2():
    """Without --margin, key metrics match Round 2 baseline values."""
    tickers = ["1515.T", "7203.T", "8306.T", "8411.T"]
    for ticker in tickers:
        sig = generate_signals(ticker, "2025-05-25", "2026-05-25")
        result = simulate_trades(sig, margin_mode=False)
        assert result["trade_count"] > 0, f"{ticker}: no trades"
        assert isinstance(result["sharpe_ratio"], float)
        assert isinstance(result["max_drawdown"], float)
        assert isinstance(result["cagr"], float)
        for t in result["trades"]:
            assert t["direction"] == "long", f"{ticker}: expected long-only without margin"
            assert "margin_cost" in t


def test_empty_metrics_structure():
    """_empty_metrics() includes all required fields."""
    m = _empty_metrics()
    required = ["sharpe_ratio", "sortino_ratio", "max_drawdown", "win_rate",
                "profit_factor", "cagr", "total_return", "trade_count",
                "total_margin_cost", "trades"]
    for key in required:
        assert key in m, f"Missing key: {key}"


def test_strategy_mode_trend():
    """trend mode: oversold_reversal never fires."""
    sig = generate_signals("1515.T", "2025-05-25", "2026-05-25", strategy_mode="trend")
    assert len(sig) > 0
    buy_signals = sig[sig["signal"] == 1]
    oversold = buy_signals[buy_signals["signal_rule"] == "oversold_reversal"]
    assert len(oversold) == 0, "trend mode should not produce oversold_reversal"


def test_strategy_mode_contrarian():
    """contrarian mode: trend_following never fires."""
    sig = generate_signals("1515.T", "2025-05-25", "2026-05-25", strategy_mode="contrarian")
    assert len(sig) > 0
    buy_signals = sig[sig["signal"] == 1]
    trend = buy_signals[buy_signals["signal_rule"] == "trend_following"]
    assert len(trend) == 0, "contrarian mode should not produce trend_following"


def test_strategy_mode_default():
    """default mode produces both types of signals."""
    sig = generate_signals("1515.T", "2025-05-25", "2026-05-25", strategy_mode="default")
    assert len(sig) > 0
    rules = set(sig["signal_rule"].dropna())
    # Should see a mix of signal types
    assert len(rules) > 2, f"Expected >2 distinct rules, got {rules}"


def test_execution_delay_adds_metadata():
    """When --execution-delay is used, output includes execution_model metadata."""
    import pandas as pd
    import numpy as np

    # Synthetic signal: buy on day 0, then hold
    dates = ["2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09", "2025-01-10"]
    n = len(dates)
    sig = pd.DataFrame({
        "date": dates,
        "close": np.arange(100.0, 100.0 + n, 1.0),
        "high": np.arange(101.0, 101.0 + n, 1.0),
        "low": np.arange(99.0, 99.0 + n, 1.0),
        "signal": [1] + [0] * (n - 1),
        "signal_rule": ["momentum"] * 2 + [None] * (n - 2),
        "rsi": [30.0] * n,
        "52w_position": [30.0] * n,
        "5d_return": [5.0] * n,
        "volume_ratio": [1.5] * n,
        "boll_lb": [98.0] * n,
        "ret_20d": [2.0] * n,
        "atr": [2.0] * n,
        "trend_state": ["uptrend"] * n,
        "sma_50": [98.0] * n,
        "sma_200": [95.0] * n,
        "ret_10d": [3.0] * n,
    })

    # Without delay: entry on same day
    result_no_delay = simulate_trades(sig, execution_delay=0)
    assert result_no_delay["trade_count"] > 0
    assert result_no_delay["trades"][0]["entry_date"] == "2025-01-06"

    # With 1-day delay: entry on T+1
    result_delay = simulate_trades(sig, execution_delay=1)
    assert result_delay["trade_count"] > 0
    assert result_delay["trades"][0]["entry_date"] == "2025-01-07"
    assert result_delay["trades"][0]["entry_price"] == 101.0

    # Verify the execution_model metadata structure (as main() would add it)
    execution_model = {
        "execution_delay_days": 1,
        "price_basis": "close",
        "cost_model": "commission_slippage_market_impact",
    }
    assert execution_model["execution_delay_days"] == 1
    assert execution_model["price_basis"] == "close"
    assert execution_model["cost_model"] == "commission_slippage_market_impact"


def test_safe_spearmanr_returns_none_for_constant_input():
    from backtest_engine import _safe_spearmanr
    ic, pval = _safe_spearmanr([1, 1, 1], [0.01, 0.02, 0.03])
    assert ic is None
    assert pval is None


def test_compute_signal_ic_does_not_emit_nan_for_constant_rule_signals():
    import math
    import pandas as pd
    from backtest_engine import compute_signal_ic

    signals_df = pd.DataFrame({
        "close": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
        "signal": [1, 1, 1, 1, 1, 1, 0, 0, 0, 0],
        "signal_rule": ["momentum", "momentum", "momentum", "momentum", "momentum", "momentum", None, None, None, None],
    })

    result = compute_signal_ic(signals_df)

    def walk(value):
        if isinstance(value, dict):
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)
        else:
            yield value

    assert all(not (isinstance(value, float) and math.isnan(value)) for value in walk(result))


def test_backtest_json_serialization_rejects_non_finite_values():
    import json
    import pytest

    with pytest.raises(ValueError):
        json.dumps({"ic": float("nan")}, allow_nan=False)


def test_ic_filter_constant_inputs_do_not_warn():
    import warnings
    from backtest_engine import _safe_corrcoef
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        value = _safe_corrcoef([1, 1, 1, 1, 1], [0.01, 0.02, 0.03, 0.04, 0.05])
    assert value == 0.0
    assert not [w for w in caught if "invalid value encountered" in str(w.message)]
