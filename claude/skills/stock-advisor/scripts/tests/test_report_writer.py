# stock-advisor/scripts/tests/test_report_writer.py
import json, tempfile
from pathlib import Path
from report_writer import build_report, _format_forecast_row, _yen

MOCK_DAILY_ACTIONS = {
    "generated_at": "2026-07-01T08:05:00+09:00",
    "account": {
        "total_assets": 18000000, "available_cash": 1800000,
        "margin_ratio": 35.58, "buying_power": 1780000,
        "margin_principal": 33225000,
    },
    "actions": [{
        "ticker": "5803", "name": "フジクラ",
        "holdings": [{"type": "現物", "name": "フジクラ", "quantity": 700,
                       "cost_price": 4982, "current_price": 6131,
                       "pnl_pct": 23.06, "weight_pct": 23.58, "account": "特定"}],
        "analysis": {
            "investment_rating": "HOLD", "execution_posture": "NO_TRADE",
            "reasoning": "短期モメンタム強いが期待リターンマイナス",
            "fundamental_rating": "HOLD", "technical_direction": "BUY",
            "risk_flags": [],
        },
        "today_action": "NO_TRADE", "overridden": False, "override_reason": None,
        "order_candidates": [], "triggers": ["2026-08-06 1Q決算"],
    }],
    "errors": {"holdings": [], "watchlist": []},
    "summary": {"total_positions": 1, "action_needed": [], "monitor": ["5803"],
                 "reduce_candidates": [], "buy_candidates": []},
}

MOCK_ANALYSIS_V2 = {
    "schema_version": "2.0", "ticker": "5803",
    "technical": {
        "direction": "BUY", "signal_raw": "HOLD_BUY", "score": 22,
        "trend_state": "strong_uptrend",
        "indicators": {
            "close": 6131, "atr": 491, "rsi": 60.4,
            "macd": {"line": 270.4, "signal": 29.2, "histogram": 241.2},
            "bollinger": {"position_pct": 85.4},
            "sma_25": 5043, "sma_75": 5156,
            "volatility_annual_pct": 59.0,
        },
        "signals": [], "backtest": {},
    },
    "fundamental": {
        "rating": "HOLD", "scenarios": [
            {"label": "強気", "price": 7500, "probability": 0.3},
            {"label": "中立", "price": 5670, "probability": 0.5},
            {"label": "弱気", "price": 3300, "probability": 0.2},
        ],
        "investment_thesis": "テスト判断",
        "catalysts": ["2026-08-06 1Q決算"],
        "monitoring_triggers": ["月次光ケーブル市況"],
    },
    "integrated": {"investment_rating": "HOLD", "execution_posture": "NO_TRADE",
                    "reasoning": "テスト", "risk_flags": []},
    "forecast": {
        "target": "next_session", "target_date": "2026-07-01",
        "base_price": 6131,
        "ohlc": {"open": 6149, "high": 6710, "low": 5915, "close": 6250},
        "confidence": "low",
        "unavailable_reason": None,
        "inputs": {"close": 6131, "atr": 491},
        "bias": {"direction": "up", "strength": "moderate",
                 "upside_atr_multiple": 1.18, "downside_atr_multiple": 0.74},
        "reasoning": "短期モメンタム強いがBB位置高く上値限定的。",
    },
}

def test_build_report_generates_markdown():
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        da_path = tmpdir / "daily_actions.json"
        da_path.write_text(json.dumps(MOCK_DAILY_ACTIONS))
        ticker_dir = tmpdir / "5803"
        ticker_dir.mkdir()
        (ticker_dir / "latest.json").write_text(json.dumps({
            "latest_run_id": "test-run", "latest_status": "completed",
            "latest_rating": "HOLD",
        }))
        run_dir = ticker_dir / "runs" / "test-run"
        run_dir.mkdir(parents=True)
        (run_dir / "analysis.json").write_text(json.dumps(MOCK_ANALYSIS_V2))

        report = build_report(da_path, tmpdir)

    assert "ポートフォリオ日次レポート" in report
    assert "フジクラ" in report
    assert "¥6,131" in report
    assert "翌営業日の4本値目安" in report
    assert "| ¥6,149 | ¥6,710 | ¥5,915 | ¥6,250 |" in report

def test_yen_formatter():
    assert _yen(6131) == "¥6,131"
    assert _yen(1000000) == "¥1,000,000"
    assert _yen(None) == "-"

def test_format_forecast_row_normal():
    row = _format_forecast_row(MOCK_ANALYSIS_V2["forecast"])
    assert "¥6,149" in row
    assert "¥6,710" in row
    assert "low" in row

def test_format_forecast_row_unavailable():
    row = _format_forecast_row({
        "confidence": "unavailable", "unavailable_reason": "missing_atr",
        "ohlc": None, "base_price": None, "target": "next_session",
    })
    assert "データ不足" in row
    assert "missing_atr" in row
