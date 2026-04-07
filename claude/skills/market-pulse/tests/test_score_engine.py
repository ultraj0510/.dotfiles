# tests/test_score_engine.py
import os
import csv
import tempfile
import pytest
from scripts.score_engine import (
    load_strategy,
    compute_macro_multiplier,
    score_holding,
    append_daily_scores,
    read_latest_score,
    record_trade_entry,
    record_trade_exit,
)

# ── テスト用フィクスチャ ─────────────────────────────────────────

MINIMAL_STRATEGY = {
    "version": 1,
    "signals": {
        "rsi_oversold":    {"score": 20,  "threshold": 35},
        "rsi_overbought":  {"score": -20, "threshold": 68},
        "bb_lower_touch":  {"score": 15,  "threshold": 0.02},
        "bb_upper_touch":  {"score": -15, "threshold": 0.02},
        "w52_low":         {"score": 10,  "threshold": 15},
        "w52_high":        {"score": -10, "threshold": 85},
        "momentum_surge":  {"score": 12,  "threshold": 7.0},
        "analyst_upside":  {"score": 15,  "threshold": 25},
        "analyst_downside":{"score": -15, "threshold": -15},
        "short_squeeze":   {"score": 8,   "threshold": 10},
        "pnl_loss":        {"score": -25, "threshold": -15},
        "pnl_profit":      {"score": 20,  "threshold": 30},
    },
    "macro_multipliers": {
        "vix_risk_off":  {"multiplier": 0.6, "threshold": 25},
        "vix_risk_on":   {"multiplier": 1.2, "threshold": 13},
        "sp500_down":    {"multiplier": 0.7, "threshold": -1.5},
        "sp500_up":      {"multiplier": 1.1, "threshold": 1.0},
        "usdjpy_strong": {"multiplier": 1.1, "threshold": 155},
        "usdjpy_weak":   {"multiplier": 0.9, "threshold": 140},
    },
    "action_thresholds": {"buy": 25, "sell": -25, "action_flag": 15},
}

NEUTRAL_MACRO = {
    "^VIX":     {"latest": 18.0, "change_1d": 0.5},
    "^GSPC":    {"latest": 5000, "change_1d": 0.3},
    "USDJPY=X": {"latest": 148.0},
}

RISK_OFF_MACRO = {
    "^VIX":     {"latest": 30.0, "change_1d": 5.0},
    "^GSPC":    {"latest": 4800, "change_1d": -2.5},
    "USDJPY=X": {"latest": 148.0},
}

# ── load_strategy ──────────────────────────────────────────────

def test_load_strategy_returns_defaults_when_missing():
    result = load_strategy("/nonexistent/path/strategy.yaml")
    assert "signals" in result
    assert "rsi_oversold" in result["signals"]
    assert "action_thresholds" in result

def test_load_strategy_reads_file(tmp_path):
    import yaml
    s = {"version": 1, "signals": {"rsi_oversold": {"score": 99, "threshold": 40}},
         "macro_multipliers": {}, "action_thresholds": {"buy": 10, "sell": -10, "action_flag": 5}}
    p = tmp_path / "strategy.yaml"
    p.write_text(yaml.dump(s))
    result = load_strategy(str(p))
    assert result["signals"]["rsi_oversold"]["score"] == 99

# ── compute_macro_multiplier ────────────────────────────────────

def test_compute_macro_multiplier_neutral():
    m = compute_macro_multiplier(NEUTRAL_MACRO, MINIMAL_STRATEGY)
    assert m == pytest.approx(1.0)

def test_compute_macro_multiplier_vix_risk_off():
    m = compute_macro_multiplier(RISK_OFF_MACRO, MINIMAL_STRATEGY)
    # VIX≥25 → 0.6, S&P500≤-1.5% → 0.7  →  0.6 * 0.7 = 0.42
    assert m == pytest.approx(0.42)

def test_compute_macro_multiplier_vix_risk_on():
    macro = {"^VIX": {"latest": 10.0, "change_1d": -1.0},
             "^GSPC": {"latest": 5000, "change_1d": 0.2},
             "USDJPY=X": {"latest": 148.0}}
    m = compute_macro_multiplier(macro, MINIMAL_STRATEGY)
    assert m == pytest.approx(1.2)

# ── score_holding ───────────────────────────────────────────────

def test_score_holding_rsi_oversold():
    holding  = {"ticker": "7974.T", "cost_price": 10000, "position_type": "現物"}
    metrics  = {"current": 9800, "rsi": 28.0, "pos_52w": 50.0,
                "ret_5d": 1.0, "bb_lower": 9600, "bb_upper": 10400, "bb_mid": 10000,
                "notable": []}
    analyst  = {}
    result   = score_holding(holding, metrics, analyst, NEUTRAL_MACRO, MINIMAL_STRATEGY)
    assert "rsi_oversold" in result["signals_fired"]
    assert result["raw_score"] == 20

def test_score_holding_macro_reduces_positive_score():
    holding  = {"ticker": "7974.T", "cost_price": 10000, "position_type": "現物"}
    metrics  = {"current": 9800, "rsi": 28.0, "pos_52w": 50.0,
                "ret_5d": 1.0, "bb_lower": 9600, "bb_upper": 10400, "bb_mid": 10000,
                "notable": []}
    analyst  = {}
    neutral  = score_holding(holding, metrics, analyst, NEUTRAL_MACRO, MINIMAL_STRATEGY)
    risk_off = score_holding(holding, metrics, analyst, RISK_OFF_MACRO, MINIMAL_STRATEGY)
    assert risk_off["adjusted_score"] < neutral["adjusted_score"]
    assert risk_off["macro_multiplier"] == pytest.approx(0.42)

def test_score_holding_multiple_signals():
    holding  = {"ticker": "TEST.T", "cost_price": 10000, "position_type": "現物"}
    # RSI 28 (oversold +20), 52週位置 10% (w52_low +10), 含み損 -20% (pnl_loss -25)
    metrics  = {"current": 8000, "rsi": 28.0, "pos_52w": 10.0,
                "ret_5d": 1.0, "bb_lower": 9600, "bb_upper": 10400, "bb_mid": 10000,
                "notable": []}
    analyst  = {}
    result   = score_holding(holding, metrics, analyst, NEUTRAL_MACRO, MINIMAL_STRATEGY)
    assert "rsi_oversold" in result["signals_fired"]
    assert "w52_low" in result["signals_fired"]
    assert "pnl_loss" in result["signals_fired"]
    assert result["raw_score"] == 20 + 10 - 25  # = +5

def test_score_holding_action_flag_above_threshold():
    holding  = {"ticker": "TEST.T", "cost_price": 10000, "position_type": "現物"}
    # RSI 28 +20, w52_low +10 → raw=30, adjusted=30 (neutral macro) → action_flag=True
    metrics  = {"current": 9800, "rsi": 28.0, "pos_52w": 10.0,
                "ret_5d": 1.0, "bb_lower": 9600, "bb_upper": 10400, "bb_mid": 10000,
                "notable": []}
    analyst  = {}
    result   = score_holding(holding, metrics, analyst, NEUTRAL_MACRO, MINIMAL_STRATEGY)
    assert result["action_flag"] is True

def test_score_holding_credit_under_60_days_forces_action_flag():
    from datetime import date, timedelta
    expiry = (date.today() + timedelta(days=30)).isoformat()
    holding = {"ticker": "TEST.T", "cost_price": 10000, "position_type": "信用",
               "expiry_date": expiry}
    metrics = {"current": 10100, "rsi": 50.0, "pos_52w": 50.0,
               "ret_5d": 0.5, "bb_lower": 9600, "bb_upper": 10400, "bb_mid": 10000,
               "notable": []}
    analyst = {}
    result  = score_holding(holding, metrics, analyst, NEUTRAL_MACRO, MINIMAL_STRATEGY)
    assert result["action_flag"] is True  # 残30日なので強制 True

def test_score_holding_credit_over_60_days_no_forced_flag():
    from datetime import date, timedelta
    expiry = (date.today() + timedelta(days=90)).isoformat()
    holding = {"ticker": "TEST.T", "cost_price": 10000, "position_type": "信用",
               "expiry_date": expiry}
    metrics = {"current": 10100, "rsi": 50.0, "pos_52w": 50.0,
               "ret_5d": 0.5, "bb_lower": 9600, "bb_upper": 10400, "bb_mid": 10000,
               "notable": []}
    analyst = {}
    result  = score_holding(holding, metrics, analyst, NEUTRAL_MACRO, MINIMAL_STRATEGY)
    # スコアは低い（発火なし）→ action_flag は False
    assert result["action_flag"] is False

def test_score_holding_empty_metrics_returns_zero():
    holding = {"ticker": "TEST.T", "cost_price": 10000, "position_type": "現物"}
    result  = score_holding(holding, {}, {}, NEUTRAL_MACRO, MINIMAL_STRATEGY)
    assert result["raw_score"] == 0
    assert result["signals_fired"] == []
    assert result["action_flag"] is False

# ── CSV I/O ─────────────────────────────────────────────────────

def test_append_and_read_daily_scores(tmp_path):
    data_dir = str(tmp_path)
    holdings_scores = [
        {
            "date": "2026-04-06",
            "ticker": "7974.T",
            "position_type": "現物",
            "raw_score": 30,
            "adjusted_score": 25.0,
            "macro_multiplier": 1.0,
            "signals_fired": "rsi_oversold,w52_low",
            "current_price": 9800,
            "rsi": 28.0,
            "bb_pos": 0.05,
            "w52_pos": 12.0,
            "action_flag": True,
        }
    ]
    append_daily_scores(holdings_scores, data_dir)
    result = read_latest_score("7974.T", "現物", data_dir)
    assert result is not None
    assert float(result["adjusted_score"]) == pytest.approx(25.0)
    assert result["signals_fired"] == "rsi_oversold,w52_low"

def test_read_latest_score_returns_none_when_no_data(tmp_path):
    result = read_latest_score("9999.T", "現物", str(tmp_path))
    assert result is None

def test_record_trade_entry_and_exit(tmp_path):
    data_dir = str(tmp_path)
    score_data = {"adjusted_score": 28.0, "signals_fired": "rsi_oversold"}
    record_trade_entry(
        date="2026-04-06", ticker="7974.T", action="BUY",
        qty=100, price=9800.0, position_type="現物",
        cost_price=9800.0, score_data=score_data, data_dir=data_dir
    )
    record_trade_exit(
        ticker="7974.T", position_type="現物",
        exit_date="2026-05-10", exit_price=10500.0, exit_qty=100,
        data_dir=data_dir
    )
    log_path = os.path.join(data_dir, "trade_log.csv")
    with open(log_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["exit_price"] == "10500.0"
    assert float(rows[0]["pnl_pct"]) == pytest.approx((10500.0 / 9800.0 - 1) * 100)
