import json
import subprocess
import sys
from pathlib import Path

from html_report_builder import build_html, CSS


def test_html_report_contains_daily_sections():
    html = build_html({
        "reference_date": "2026-06-01",
        "account": {
            "total_assets": 19661379, "available_cash": 624634,
            "margin_ratio_label": "委託保証金率", "margin_ratio_text": "1124.46%",
        },
        "price_freshness": {"stale_count": 0, "stale_tickers": []},
        "strategy_review": {
            "risk_mode": "balanced", "automation_allowed": 1,
            "validated_strategy": 0, "candidate_strategy": 1, "hold_baseline": 9,
            "profit_protection": 0, "candidates": {"7974.T": {"strategy": "trend"}},
        },
        "holdings": [{"ticker": "7974.T", "name": "任天堂", "position_type": "現物", "quantity": 100, "cost_price": 6945, "current_price": 7242, "price_source": "regularMarketPrice", "price_as_of": "2026-06-01T10:25:52+09:00"}],
        "signals": {"7974.T": {"score": {"score": 23, "recommendation": "HOLD_BUY"}, "indicators": {"rsi": "40.62", "atr": "264.62"}}},
        "backtest": {"7974.T": {
            "baseline": {"trade_count": 23, "win_rate": 47.83, "sharpe_ratio": -0.1034},
            "walk_forward": {"verdict": "unstable", "consensus": {"data_quality": "thin_oos_trades", "total_test_trades": 7}},
            "strategy_comparison": {"trend": {"benchmark_comparison": {"strategy_total_return": 26.90, "benchmark_total_return": 22.05, "excess_total_return": 4.85}}},
        }},
        "quant_decisions": {"decisions": {"7974.T": {"report_action": "NO_TRADE", "order_shares": 0, "vetoes": ["negative_ev"], "risk_flags": ["candidate_strategy_reduced_size"], "explanations": ["negative EV blocks BUY"], "risk_posture": "neutral"}}},
        "watchlist": [],
    })
    assert "<!DOCTYPE html>" in html
    assert "Stock Advisor Daily" in html
    assert "戦略ゲート" in html
    assert "7974.T" in html
    assert "negative_ev: negative EV blocks BUY" in html
    assert "判断理由" in html
    assert "注意点" in html
    assert "シグナル" in html
    assert "HOLD_BUY" in html
    assert "買い見送り" in html
    assert "価格ソース" in html
    assert "regularMarketPrice" in html
    assert "価格時刻" in html
    assert "2026-06-01T10:25:52+09:00" in html
    assert "RSI" in html
    assert "40.6" in html
    assert "ATR（日次値幅）" in html


def test_html_report_escapes_json_values():
    html = build_html({
        "reference_date": "2026-06-01",
        "account": {},
        "holdings": [{"ticker": "9999.T", "name": "<script>alert(1)</script>", "position_type": "現物", "quantity": 1, "cost_price": 100, "current_price": 110}],
        "signals": {},
        "backtest": {},
        "quant_decisions": {"decisions": {"9999.T": {"report_action": "HOLD", "order_shares": 0}}},
        "watchlist": [],
    })
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_cli_updates_sibling_manifest_with_html_report(tmp_path):
    context = tmp_path / "report_context.json"
    output = tmp_path / "report.html"
    manifest = tmp_path / "run_manifest.json"
    context.write_text(json.dumps({
        "reference_date": "2026-06-01",
        "account": {}, "holdings": [], "signals": {}, "backtest": {},
        "quant_decisions": {"decisions": {}}, "watchlist": [],
    }), encoding="utf-8")
    manifest.write_text(json.dumps({
        "generated_at": "2026-06-01T10:42:23",
        "artifacts": {"report_context": str(context)},
    }), encoding="utf-8")

    script = Path(__file__).resolve().parents[1] / "html_report_builder.py"
    subprocess.run([sys.executable, str(script), "--context", str(context), "-o", str(output)], check=True)

    updated = json.loads(manifest.read_text(encoding="utf-8"))
    assert updated["artifacts"]["html_report"] == str(output)


def test_html_report_is_static_and_mobile_safe():
    html = build_html({
        "reference_date": "2026-06-01", "account": {}, "holdings": [],
        "signals": {}, "backtest": {}, "quant_decisions": {"decisions": {}}, "watchlist": [],
    })
    assert "<script" not in html.lower()
    assert "https://" not in html
    assert "http://" not in html
    assert "overflow-wrap:anywhere" in CSS
    assert "min-width:0" in CSS
