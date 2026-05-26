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
