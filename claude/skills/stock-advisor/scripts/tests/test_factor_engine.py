"""Tests for factor engine (A1) and arbitration matrix (Phase 3)."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestFactorEngine:

    def test_module_imports(self):
        from factor_engine import (compute_factors, classify_factor_signal,
                                    _z_score, MIN_FACTORS_REQUIRED, FACTOR_NAMES)
        assert callable(compute_factors)
        assert callable(classify_factor_signal)
        assert MIN_FACTORS_REQUIRED == 2
        assert len(FACTOR_NAMES) == 4

    def test_z_score_clamped(self):
        from factor_engine import _z_score
        assert _z_score(100, 14) == 3.0
        assert _z_score(-100, 14) == -3.0
        assert _z_score(14, 14) == 0.0

    def test_z_score_none_value(self):
        from factor_engine import _z_score
        assert _z_score(None, 14) == 0.0

    def test_classify_signal_boundaries(self):
        from factor_engine import classify_factor_signal
        assert classify_factor_signal(1.5) == "STRONG_BUY"
        assert classify_factor_signal(0.5) == "BUY"
        assert classify_factor_signal(0.0) == "NEUTRAL"
        assert classify_factor_signal(-0.5) == "SELL"
        assert classify_factor_signal(-1.5) == "STRONG_SELL"
        assert classify_factor_signal(None) is None

    def test_compute_factors_returns_structure(self):
        from factor_engine import compute_factors
        result = compute_factors("7974.T")
        assert "ticker" in result
        assert "composite_z" in result
        assert "data_coverage" in result
        assert "factor_scores" in result
        for fn in ["value", "momentum", "quality", "volatility"]:
            assert fn in result["factor_scores"]

    def test_compute_factors_coverage_format(self):
        from factor_engine import compute_factors
        result = compute_factors("7974.T")
        parts = result["data_coverage"].split("/")
        assert len(parts) == 2
        assert 0 <= int(parts[0]) <= 4

    def test_empty_data_returns_null_composite(self):
        from factor_engine import compute_factors
        result = compute_factors("1328.T")
        parts = result["data_coverage"].split("/")
        if int(parts[0]) < 2:
            assert result["composite_z"] is None


class TestArbitrationMatrix:

    def test_module_import(self):
        from trade_advisor import arbitrate_factor_vs_rule
        assert callable(arbitrate_factor_vs_rule)

    def test_strong_buy_with_sell_is_neutral(self):
        from trade_advisor import arbitrate_factor_vs_rule
        r = arbitrate_factor_vs_rule("STRONG_BUY", "SELL")
        assert r["action"] == "NEUTRAL"

    def test_strong_sell_with_sell_is_exit(self):
        from trade_advisor import arbitrate_factor_vs_rule
        r = arbitrate_factor_vs_rule("STRONG_SELL", "SELL")
        assert r["action"] == "EXIT"
        assert r["adjustment"] == 0.0

    def test_neutral_defers_to_binary(self):
        from trade_advisor import arbitrate_factor_vs_rule
        r = arbitrate_factor_vs_rule("NEUTRAL", "BUY_MORE")
        assert r["action"] == "WEIGHT"

    def test_sell_capped_by_buy(self):
        from trade_advisor import arbitrate_factor_vs_rule
        r = arbitrate_factor_vs_rule("SELL", "STRONG_BUY")
        assert r["action"] == "WEIGHT"

    def test_none_factor_binary_only(self):
        from trade_advisor import arbitrate_factor_vs_rule
        r = arbitrate_factor_vs_rule(None, "HOLD")
        assert r["action"] == "BINARY_ONLY"

    def test_all_combinations_valid(self):
        from trade_advisor import arbitrate_factor_vs_rule
        for fs in ["STRONG_BUY", "BUY", "NEUTRAL", "SELL", "STRONG_SELL", None]:
            for bo in ["STRONG_BUY", "BUY_MORE", "HOLD", "REDUCE", "SELL"]:
                r = arbitrate_factor_vs_rule(fs, bo)
                assert 0.0 <= r["adjustment"] <= 1.25
