# tests/test_tune_strategy.py
import csv
import os
import pytest


def _write_trade_log(path, rows):
    fields = [
        "date", "ticker", "action", "quantity", "price", "position_type", "cost_price",
        "score_at_entry", "signals_at_entry",
        "exit_date", "exit_price", "exit_quantity", "pnl_pct", "pnl_jpy",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_analyze_returns_signal_stats(tmp_path):
    import sys
    skill_dir = os.path.dirname(os.path.dirname(__file__))
    sys.path.insert(0, os.path.join(skill_dir, "scripts"))
    from tune_strategy import analyze_signals

    log = tmp_path / "trade_log.csv"
    _write_trade_log(str(log), [
        {"date": "2026-04-01", "ticker": "A.T", "action": "BUY", "quantity": 100,
         "price": 1000, "position_type": "現物", "cost_price": 1000,
         "score_at_entry": 30, "signals_at_entry": "rsi_oversold,w52_low",
         "exit_date": "2026-04-10", "exit_price": 1100, "exit_quantity": 100,
         "pnl_pct": 10.0, "pnl_jpy": 10000},
        {"date": "2026-04-02", "ticker": "B.T", "action": "BUY", "quantity": 100,
         "price": 2000, "position_type": "現物", "cost_price": 2000,
         "score_at_entry": 20, "signals_at_entry": "rsi_oversold",
         "exit_date": "2026-04-12", "exit_price": 1900, "exit_quantity": 100,
         "pnl_pct": -5.0, "pnl_jpy": -10000},
        {"date": "2026-04-03", "ticker": "C.T", "action": "BUY", "quantity": 100,
         "price": 3000, "position_type": "現物", "cost_price": 3000,
         "score_at_entry": 25, "signals_at_entry": "rsi_oversold,bb_lower_touch",
         "exit_date": "2026-04-15", "exit_price": 3300, "exit_quantity": 100,
         "pnl_pct": 10.0, "pnl_jpy": 30000},
    ])
    stats = analyze_signals(str(log), min_trades=1)
    # rsi_oversold: 3件 勝2負1 → 勝率0.667
    assert "rsi_oversold" in stats
    assert stats["rsi_oversold"]["trades"] == 3
    assert abs(stats["rsi_oversold"]["win_rate"] - 2/3) < 0.01
    # w52_low: 1件 勝1 → 勝率1.0
    assert "w52_low" in stats
    assert stats["w52_low"]["win_rate"] == pytest.approx(1.0)


def test_recommend_adjustments(tmp_path):
    import sys
    skill_dir = os.path.dirname(os.path.dirname(__file__))
    sys.path.insert(0, os.path.join(skill_dir, "scripts"))
    from tune_strategy import recommend_adjustments

    stats = {
        "rsi_oversold": {"trades": 12, "win_rate": 0.75, "avg_pnl": 5.0},  # 高勝率 → UP
        "w52_low":      {"trades": 10, "win_rate": 0.40, "avg_pnl": -1.0}, # 低勝率 → DOWN
        "bb_lower_touch": {"trades": 3, "win_rate": 0.60, "avg_pnl": 2.0}, # 少ない → skip
    }
    recs = recommend_adjustments(stats, min_trades=5)
    tickers_rec = {r["signal"]: r["direction"] for r in recs}
    assert tickers_rec.get("rsi_oversold") == "up"
    assert tickers_rec.get("w52_low") == "down"
    assert "bb_lower_touch" not in tickers_rec  # min_trades 未満
