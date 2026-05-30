"""Tests for report_skeleton_builder.py"""
import json
import os
import subprocess
import tempfile

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = os.path.join(SCRIPTS_DIR, ".venv", "bin", "python")
BUILDER = os.path.join(SCRIPTS_DIR, "report_skeleton_builder.py")
FIXTURE_DIR = os.path.join(SCRIPTS_DIR, "tests", "fixtures", "report_quality")


def test_skeleton_builder_outputs_required_sections():
    with tempfile.TemporaryDirectory() as tmpdir:
        ctx = os.path.join(tmpdir, "report_context.json")
        report = os.path.join(tmpdir, "report.md")
        subprocess.run([
            PYTHON, os.path.join(SCRIPTS_DIR, "report_context_builder.py"),
            "--portfolio", os.path.join(FIXTURE_DIR, "portfolio.yaml"),
            "--signals", os.path.join(FIXTURE_DIR, "signals.json"),
            "--backtest-dir", os.path.join(FIXTURE_DIR, "backtest"),
            "--portfolio-analytics", os.path.join(FIXTURE_DIR, "portfolio_analytics.json"),
            "--quant-decisions", os.path.join(FIXTURE_DIR, "quant_decisions.json"),
            "-o", ctx,
        ], check=True)
        subprocess.run([PYTHON, BUILDER, "--context", ctx, "-o", report], check=True)
        text = open(report).read()
    assert "## 株式分析" in text
    assert "## 取引指示一覧" in text
    assert "## 銘柄別詳細" in text
    assert "## 本日の優先アクション" in text


def test_skeleton_uses_validator_compatible_position_headings_and_labels():
    from report_skeleton_builder import build_report, risk_posture_ja

    context = {
        "reference_date": "2026-05-30",
        "account": {"total_assets": 1000000, "available_cash": 50000},
        "holdings": [
            {"ticker": "5803.T", "name": "フジクラ", "position_type": "現物",
             "quantity": 200, "cost_price": 4200, "current_price": 4820},
        ],
        "watchlist": [],
        "signals": {},
        "backtest": {},
        "correlations": {},
        "quant_decisions": {
            "decisions": {
                "5803.T": {
                    "report_action": "REDUCE",
                    "order_shares": 100,
                    "unrealized_pnl_pct": 14.76,
                    "risk_posture": "protect_profit",
                    "protective_stop_price": 4500,
                }
            }
        },
    }

    report = build_report(context)

    # Heading uses en-dash with spaces and action_ja
    assert "（現物） — 一部売却（+14.76%）" in report, \
        "Expected heading format: （position_type） — action_ja（pnl%）"

    # Labels use validator-compatible names
    assert "含み損益率" in report, "Expected 含み損益率"
    assert "リスク姿勢" in report, "Expected リスク姿勢"
    assert "ストップ目安価格" in report, "Expected ストップ目安価格"
    assert "利益保護" in report, "Expected risk_posture_ja output for protect_profit"
    assert "リスクポスチャー" not in report, "Old label リスクポスチャー should not appear"
    assert "ストップ標準価格" not in report, "Old label ストップ標準価格 should not appear"


def test_skeleton_displays_risk_flags_separately_from_vetoes_and_formats_neutral():
    from report_skeleton_builder import build_report

    report = build_report({
        "account": {},
        "holdings": [
            {"ticker": "5803.T", "name": "フジクラ", "position_type": "現物", "quantity": 200, "cost_price": 4600, "current_price": 4771},
            {"ticker": "1515.T", "name": "日鉄鉱", "position_type": "現物", "quantity": 3000, "cost_price": 3552, "current_price": 2397},
        ],
        "signals": {},
        "backtest": {},
        "quant_decisions": {
            "decisions": {
                "5803.T": {
                    "report_action": "REDUCE",
                    "order_shares": 300,
                    "order_type": "limit",
                    "limit_price": 4771,
                    "vetoes": [],
                    "risk_flags": ["negative_walk_forward"],
                    "risk_posture": "neutral",
                },
                "1515.T": {
                    "report_action": "HOLD",
                    "order_shares": 0,
                    "vetoes": [],
                    "risk_flags": ["position_over_cap_loss_concentration"],
                    "risk_posture": "rebalance_on_strength",
                    "advisory_plan": {
                        "mode": "trim_on_rebound_rebuy_on_pullback",
                        "trim_shares": 300,
                        "trim_trigger_price": 2440.4,
                        "reentry_watch_price": 2162.25,
                        "max_reentry_shares": 300,
                        "reentry_allowed_after_trim": True,
                        "reentry_requires": ["trim_filled", "price_near_lower_band", "rsi_below_40_or_reversal_signal"],
                    },
                },
            }
        },
    })

    assert "| 銘柄コード | 名称 | 指示 | 株数 | 注文方法 | 指値 | 注意点 |" in report
    assert "| 5803.T | フジクラ | 一部売却 | 300 | limit | ¥4,771 | negative_walk_forward |" in report
    assert "| リスク姿勢 | 通常 |" in report
    assert "| 注意点 | negative_walk_forward |" in report
    assert "| 戦略 | 反発売り・押し目買い監視 |" in report
    assert "| 反発売り目安 | ¥2,440 |" in report
    assert "| 押し目買い監視 | ¥2,162 |" in report
    assert "neutral" not in report


def test_skeleton_deduplicates_ticker_level_active_orders():
    from report_skeleton_builder import build_report

    context = {
        "reference_date": "2026-05-30",
        "account": {"total_assets": 1000000, "available_cash": 50000},
        "holdings": [
            {"ticker": "5803.T", "name": "フジクラ", "position_type": "現物",
             "quantity": 200, "cost_price": 4200, "current_price": 4820},
            {"ticker": "5803.T", "name": "フジクラ", "position_type": "信用",
             "quantity": 100, "cost_price": 5200, "current_price": 4820},
        ],
        "watchlist": [],
        "signals": {},
        "backtest": {},
        "correlations": {},
        "quant_decisions": {
            "decisions": {
                "5803.T": {
                    "report_action": "SELL",
                    "order_shares": 300,
                    "unrealized_pnl_pct": 5.0,
                    "risk_posture": "reduce_risk",
                    "protective_stop_price": None,
                }
            }
        },
    }

    report = build_report(context)

    # Count occurrences of 5803.T in active orders table area
    lines = report.splitlines()
    in_orders = False
    ticker_count = 0
    for line in lines:
        if "取引指示一覧" in line:
            in_orders = True
            continue
        if "銘柄別詳細" in line:
            in_orders = False
            continue
        if in_orders and "5803.T" in line:
            ticker_count += 1

    assert ticker_count == 1, \
        f"Expected 5803.T to appear once in active orders, got {ticker_count}"


def test_skeleton_generated_from_context_passes_validator():
    """Integration test: generate skeleton from fixtures and validate it."""
    from validate_report import validate

    with tempfile.TemporaryDirectory() as tmpdir:
        ctx = os.path.join(tmpdir, "report_context.json")
        report = os.path.join(tmpdir, "report.md")

        # Step 1: Build report context from fixtures
        subprocess.run([
            PYTHON, os.path.join(SCRIPTS_DIR, "report_context_builder.py"),
            "--portfolio", os.path.join(FIXTURE_DIR, "portfolio.yaml"),
            "--signals", os.path.join(FIXTURE_DIR, "signals.json"),
            "--backtest-dir", os.path.join(FIXTURE_DIR, "backtest"),
            "--portfolio-analytics", os.path.join(FIXTURE_DIR, "portfolio_analytics.json"),
            "--quant-decisions", os.path.join(FIXTURE_DIR, "quant_decisions.json"),
            "-o", ctx,
        ], check=True)

        # Step 2: Generate report skeleton
        subprocess.run([
            PYTHON, BUILDER, "--context", ctx, "-o", report,
        ], check=True)

        # Step 3: Validate the generated report
        errors = validate(
            report_path=report,
            signals_path=os.path.join(FIXTURE_DIR, "signals.json"),
            quant_decisions_path=os.path.join(FIXTURE_DIR, "quant_decisions.json"),
            backtest_dir=os.path.join(FIXTURE_DIR, "backtest"),
            portfolio_path=os.path.join(FIXTURE_DIR, "portfolio.yaml"),
        )

        assert errors == [], f"Validation failed: {errors}"


def test_report_shows_strategy_gate_for_untradeable_strategy():
    from report_skeleton_builder import render_strategy_gate_section

    items = [{
        "ticker": "285A.T",
        "strategy_selection": {
            "selected_strategy": "hold_baseline",
            "tradeable": False,
            "reason": "no_strategy_passed_tradeability_gate",
        },
        "benchmark_comparison": {
            "strategy_total_return": 827.86,
            "benchmark_total_return": 3727.61,
            "excess_total_return": -2899.75,
            "strategy_sharpe": 2.6337,
            "benchmark_sharpe": 3.2424,
            "excess_sharpe": -0.6087,
            "tradeable": False,
            "reason": "strategy_underperforms_benchmark",
        },
    }]

    markdown = render_strategy_gate_section(items)

    assert "## Strategy Gate" in markdown
    assert "285A.T" in markdown
    assert "hold_baseline" in markdown
    assert "strategy_underperforms_benchmark" in markdown
    assert "-2899.75" in markdown


def test_strategy_gate_table_has_matching_column_counts():
    from report_skeleton_builder import render_strategy_gate_section

    markdown = render_strategy_gate_section([{
        "ticker": "7974.T",
        "strategy_selection": {"selected_strategy": "hold_baseline", "tradeable": False},
        "benchmark_comparison": {
            "strategy_total_return": 21.25,
            "benchmark_total_return": 17.40,
            "excess_total_return": 3.85,
            "reason": "thin_oos_trades",
        },
    }])

    header, delimiter, row = [line for line in markdown.splitlines() if line.startswith("|")]
    assert header.count("|") == delimiter.count("|") == row.count("|")


def test_strategy_gate_summary_distinguishes_underperformance_from_quality_rejection():
    from report_skeleton_builder import render_strategy_gate_summary

    markdown = render_strategy_gate_summary([
        {
            "ticker": "7974.T",
            "strategy_selection": {"selected_strategy": "hold_baseline", "tradeable": False},
            "benchmark_comparison": {"beats_benchmark_return": True, "beats_benchmark_sharpe": True, "reason": "too_few_strategy_trades"},
        },
        {
            "ticker": "1515.T",
            "strategy_selection": {"selected_strategy": "hold_baseline", "tradeable": False},
            "benchmark_comparison": {"beats_benchmark_return": False, "beats_benchmark_sharpe": False, "reason": "strategy_underperforms_benchmark"},
        },
    ])

    assert "B&Hに劣後: 1銘柄" in markdown
    assert "検証品質不足: 1銘柄" in markdown
    assert "全銘柄でテクニカル戦略が買い持ち" not in markdown


def test_report_strategy_summary_mentions_manual_range_plan():
    from report_skeleton_builder import render_strategy_review_summary

    markdown = render_strategy_review_summary({
        "validated_trade_strategy": 0,
        "manual_range_plan": 1,
        "hold_baseline": 1,
    })

    assert "自動売買可: 0銘柄" in markdown
    assert "手動レンジ計画: 1銘柄" in markdown
    assert "買い持ち優先: 1銘柄" in markdown
