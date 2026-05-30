import json
import os
import tempfile
import pytest

# Add scripts dir to path for imports
import sys
_scripts_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import yaml  # available in venv
from quant_decision_engine import make_decision, load_backtest
from quant_schema import QuantDecision


def make_portfolio(holdings=None, total_assets=10_000_000, available_cash=5_000_000):
    return {
        "account": {"total_assets": total_assets, "available_cash": available_cash},
        "holdings": holdings or [],
    }


class TestMakeDecision:
    def test_positive_ev_buy_produces_buy(self):
        signal = {"action": "BUY", "current_price": 1000, "atr": 20}
        bt = {
            "total_trades": 50, "wins": 30, "losses": 20,
            "avg_win_pct": 5.0, "avg_loss_pct": -2.5,
            "walk_forward": {"sharpe_is": 1.0, "sharpe_oos": 0.8},
        }
        pf = make_portfolio(holdings=[
            {"ticker": "7203.T", "quantity": 100, "current_price": 1000, "cost_price": 950, "position_type": "現物"}
        ])
        d = make_decision("7203.T", signal, bt, pf, {})
        assert d.action == "BUY"
        assert d.order_shares > 0

    def test_negative_ev_buy_becomes_no_trade(self):
        signal = {"action": "BUY", "current_price": 1000, "atr": 20}
        bt = {
            "total_trades": 10, "wins": 3, "losses": 7,
            "avg_win_pct": 1.0, "avg_loss_pct": -3.0,
            "walk_forward": {"sharpe_is": 0.5, "sharpe_oos": 0.3},
        }
        # p_win_shrunk = (3+5)/(10+10) = 0.4
        # ev = 0.4*1.0 + 0.6*(-3.0) - 0.5 = 0.4 - 1.8 - 0.5 = -1.9
        pf = make_portfolio()
        d = make_decision("7203.T", signal, bt, pf, {})
        assert d.action == "NO_TRADE"

    def test_risk_reducing_sell_survives_negative_ev(self):
        signal = {"action": "SELL", "current_price": 1000, "atr": 20, "reduce_shares": 100}
        bt = {
            "total_trades": 10, "wins": 3, "losses": 7,
            "avg_win_pct": 1.0, "avg_loss_pct": -3.0,
            "walk_forward": {"sharpe_is": 0.5, "sharpe_oos": 0.3},
        }
        pf = make_portfolio(holdings=[
            {"ticker": "7203.T", "quantity": 100, "current_price": 1000, "cost_price": 950, "position_type": "現物"}
        ])
        d = make_decision("7203.T", signal, bt, pf, {})
        assert d.action == "SELL"
        assert d.order_type == "limit"
        assert d.limit_price is not None

    def test_hold_stays_hold(self):
        signal = {"action": "HOLD", "current_price": 1000, "atr": 20}
        pf = make_portfolio(holdings=[
            {"ticker": "7203.T", "quantity": 100, "current_price": 1000, "cost_price": 950, "position_type": "現物"}
        ])
        d = make_decision("7203.T", signal, None, pf, {})
        assert d.action == "HOLD"
        assert d.order_shares == 0

    def test_low_sample_lowers_confidence(self):
        signal = {"action": "BUY", "current_price": 1000, "atr": 20}
        bt = {
            "total_trades": 3, "wins": 2, "losses": 1,
            "avg_win_pct": 5.0, "avg_loss_pct": -2.5,
            "walk_forward": {"sharpe_is": 1.0, "sharpe_oos": 0.8},
        }
        pf = make_portfolio()
        d = make_decision("7203.T", signal, bt, pf, {})
        assert d.confidence == "low"
        assert "low_sample" in d.vetoes

    def test_empty_signal_defaults_to_hold(self):
        signal = {}
        pf = make_portfolio()
        d = make_decision("7203.T", signal, None, pf, {})
        assert d.action in ("HOLD", "NO_TRADE")
        assert d.order_shares == 0


    def test_actual_portfolio_analytics_shape_triggers_correlation_veto(self):
        signal = {"action": "BUY", "current_price": 1000, "atr": 20}
        bt = {
            "total_trades": 50, "wins": 30, "losses": 20,
            "avg_win_pct": 5.0, "avg_loss_pct": -2.5,
            "walk_forward": {"sharpe_is": 1.0, "sharpe_oos": 0.8},
        }
        pf = make_portfolio(holdings=[
            {"ticker": "7203.T", "quantity": 100, "current_price": 1000, "cost_price": 950, "position_type": "現物"},
            {"ticker": "8306.T", "quantity": 1200, "current_price": 1000, "cost_price": 900, "position_type": "現物"},
        ])
        pa = {
            "correlation": {
                "risk_concentration": "high",
                "max_correlation": {"pair": ["7203.T", "8306.T"], "value": 0.9},
            },
            "stress_test": {},
        }
        d = make_decision("7203.T", signal, bt, pf, pa)
        assert "correlation_concentration" in d.vetoes
        assert d.order_shares == 900

    def test_reduce_prefers_margin_lot_when_ticker_has_mixed_positions(self):
        signal = {"action": "REDUCE", "current_price": 4820, "atr": 150, "reduce_shares": 100}
        bt = {
            "total_trades": 18, "wins": 8, "losses": 10,
            "avg_win_pct": 2.0, "avg_loss_pct": -2.5,
            "walk_forward": {
                "sharpe_is": None, "sharpe_oos": None,
                "verdict": "insufficient_data", "overfit_detected": True,
            },
        }
        pf = make_portfolio(holdings=[
            {"ticker": "5803.T", "quantity": 200, "current_price": 4820, "cost_price": 4200, "position_type": "現物"},
            {"ticker": "5803.T", "quantity": 100, "current_price": 4820, "cost_price": 5200, "position_type": "信用", "expiry_date": "2026-07-15"},
        ])
        decision = make_decision("5803.T", signal, bt, pf, {})
        assert decision.order_shares == 100
        # Should have allocated to the margin position first
        assert len(decision.position_decisions) >= 1
        margin_allocs = [pd for pd in decision.position_decisions if pd.position_type == "信用"]
        assert len(margin_allocs) >= 1
        assert margin_allocs[0].order_shares == 100

    def test_appreciation_driven_position_over_cap_becomes_watch_veto(self):
        signal = {"action": "HOLD", "current_price": 2000, "atr": 50}
        pf = make_portfolio(
            holdings=[
                {"ticker": "1515.T", "quantity": 1500, "current_price": 2000, "cost_price": 900, "position_type": "現物"}
            ],
            total_assets=10_000_000,
        )
        decision = make_decision("1515.T", signal, None, pf, {})
        assert "position_over_cap_watch" in decision.vetoes
        assert "position_over_cap_reduce" not in decision.vetoes
        assert decision.action == "HOLD"


    def test_mixed_buy_and_overbought_sell_keeps_single_lot_winner_hold(self):
        signal = {
            "action": "HOLD",
            "current_price": 65850,
            "atr": 4695.38,
            "signals": [
                {"type": "BUY", "rule": "trend_following", "strength": "strong"},
                {"type": "BUY", "rule": "momentum", "strength": "moderate"},
                {"type": "SELL", "rule": "overbought", "strength": "moderate"},
            ],
            "indicators": {
                "close_10_ema": "58362.71",
                "boll": "50724.0",
                "boll_lb": "32223.25",
                "boll_ub": "69224.75",
                "rsi": "74.75",
                "52w_position": "100.0",
            },
        }
        bt = {
            "total_trades": 9, "wins": 7, "losses": 2,
            "avg_win_pct": 50.07, "avg_loss_pct": -10.37,
            "walk_forward": {"verdict": "unstable", "overfit_detected": False},
        }
        pf = make_portfolio(
            holdings=[{"ticker": "285A.T", "quantity": 100, "current_price": 65850, "cost_price": 15136, "position_type": "現物"}],
            total_assets=19661379, available_cash=624634,
        )
        decision = make_decision("285A.T", signal, bt, pf, {})
        # After impl: action=HOLD, order_shares=0, risk_posture=protect_profit
        assert decision.action == "HOLD"
        assert decision.order_shares == 0
        assert decision.risk_posture == "protect_profit"
        assert "single_lot_full_exit_guard" in decision.vetoes
        assert "position_over_cap_watch" in decision.vetoes
        assert decision.protective_stop_price == 58362.71
        assert decision.downside_10pct_yen == 658500

    def test_large_loss_concentration_gets_rebound_trim_plan_without_buyback(self):
        signal = {
            "action": "HOLD", "current_price": 2397, "atr": 173.98, "trend_state": "downtrend",
            "signals": [],
            "indicators": {
                "close_10_ema": "2408.45", "close_50_sma": "2561.17",
                "boll": "2440.4", "boll_lb": "2162.25", "boll_ub": "2718.55",
                "10d_return": "-8.09", "20d_return": "-1.03",
            },
        }
        bt = {
            "total_trades": 29, "wins": 10, "losses": 19,
            "avg_win_pct": 15.0, "avg_loss_pct": -4.71,
            "walk_forward": {"verdict": "insufficient_data", "overfit_detected": True},
        }
        pf = make_portfolio(
            holdings=[{"ticker": "1515.T", "quantity": 3000, "current_price": 2397, "cost_price": 3552, "position_type": "現物"}],
            total_assets=19661379, available_cash=624634,
        )
        decision = make_decision("1515.T", signal, bt, pf, {})
        assert decision.action == "HOLD"
        assert decision.order_shares == 0
        assert decision.risk_posture == "rebalance_on_strength"
        assert "position_over_cap_loss_concentration" in decision.vetoes
        assert decision.portfolio_weight_pct == 36.57
        assert decision.cost_basis_weight_pct == 54.20
        assert decision.unrealized_pnl_pct == -32.52
        assert decision.advisory_plan == {
            "mode": "trim_on_rebound",
            "trim_shares": 300,
            "trim_trigger_price": 2440.4,
            "buyback_allowed": False,
            "buyback_block_reason": "downtrend_and_position_over_30pct",
        }


class TestCLIFixture:
    """Run quant_decision_engine.py with test fixtures and verify output."""
    def test_fixture_cli_smoke(self):
        import subprocess

        fixture_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "fixtures", "quant_decision",
        )
        venv_python = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".venv", "bin", "python",
        )
        engine = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "quant_decision_engine.py",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "quant_decisions.json")
            subprocess.run(
                [
                    venv_python, engine,
                    "--portfolio", os.path.join(fixture_dir, "portfolio.yaml"),
                    "--signals", os.path.join(fixture_dir, "signals.json"),
                    "--backtest-dir", os.path.join(fixture_dir, "backtest"),
                    "--portfolio-analytics", os.path.join(fixture_dir, "portfolio_analytics.json"),
                    "-o", output,
                ],
                capture_output=True, text=True, check=True,
            )
            with open(output) as f:
                data = json.load(f)

        assert len(data["decisions"]) >= 1
        d = data["decisions"][0]
        assert d["ticker"] == "7203.T"
        assert "correlation_concentration" in d["vetoes"]
        assert d["order_shares"] == 900
        assert "risk_posture" in d
        assert "portfolio_weight_pct" in d
        assert "advisory_plan" in d


class TestLoadBacktest:
    def test_normalizes_backtest_json(self):
        """load_backtest should normalize nested backtest engine output to flat format."""
        raw = {
            "ticker": "7203.T",
            "baseline": {
                "trade_count": 50,
                "win_rate": 60.0,
                "avg_win_pct": 5.0,
                "avg_loss_pct": -3.0,
                "sharpe_ratio": 1.2,
                "max_drawdown": 15.0,
            },
            "walk_forward": {
                "train_metrics": {"sharpe_ratio": 1.5},
                "test_metrics": {"sharpe_ratio": 1.0},
                "overfit_detected": False,
                "consensus": {"verdict": "robust", "mean_sharpe": 1.1},
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "7203.T.json")
            with open(path, "w") as f:
                json.dump(raw, f)
            result = load_backtest(tmpdir, "7203.T")

        assert result is not None
        assert result["total_trades"] == 50
        assert result["wins"] == 30  # 50 * 60% = 30
        assert result["losses"] == 20
        assert result["avg_win_pct"] == 5.0
        assert result["avg_loss_pct"] == -3.0
        assert result["walk_forward"]["sharpe_is"] == 1.5
        assert result["walk_forward"]["sharpe_oos"] == 1.0
        assert result["walk_forward"]["verdict"] == "robust"

    def test_missing_file_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = load_backtest(tmpdir, "NONEXISTENT.T")
        assert result is None

    def test_already_flat_format(self):
        """load_backtest should pass through already-normalized dicts."""
        flat = {
            "total_trades": 10,
            "wins": 6,
            "losses": 4,
            "avg_win_pct": 4.0,
            "avg_loss_pct": -2.0,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "7974.T.json")
            with open(path, "w") as f:
                json.dump(flat, f)
            result = load_backtest(tmpdir, "7974.T")
        assert result["total_trades"] == 10
        assert result["wins"] == 6
        assert result["losses"] == 4

    def test_empty_json_returns_none(self):
        raw = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "EMPTY.T.json")
            with open(path, "w") as f:
                json.dump(raw, f)
            result = load_backtest(tmpdir, "EMPTY.T")
        assert result is None
