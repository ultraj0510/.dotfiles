"""Tests for volatility targeting (A3) in backtest_engine.py."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest_engine import (
    _compute_realized_vol,
    DEFAULT_RISK_PARAMS,
)


class TestComputeRealizedVol:

    def test_positive_returns(self):
        returns = [0.01, -0.005, 0.02, 0.0, 0.015]
        vol = _compute_realized_vol(returns)
        assert vol > 0

    def test_zero_returns(self):
        returns = [0.0, 0.0, 0.0, 0.0, 0.0]
        vol = _compute_realized_vol(returns)
        assert vol == 0.0

    def test_empty_returns(self):
        assert _compute_realized_vol([]) == 0.0

    def test_single_return(self):
        assert _compute_realized_vol([0.01]) == 0.0

    def test_non_annualized(self):
        returns = [0.01, -0.01, 0.02, -0.02, 0.01]
        daily = _compute_realized_vol(returns, annualize=False)
        annual = _compute_realized_vol(returns, annualize=True)
        assert round(annual / daily, 1) == round(15.87, 1)  # sqrt(252) ≈ 15.87

    def test_vol_scales_with_dispersion(self):
        low_vol = _compute_realized_vol([0.001, 0.0, -0.001, 0.002, 0.0])
        high_vol = _compute_realized_vol([0.05, -0.04, 0.06, -0.05, 0.03])
        assert high_vol > low_vol


class TestVolTargetingParams:

    def test_risk_params_has_vol_target_keys(self):
        required = {"vol_target", "vol_target_min", "vol_target_max", "vol_lookback"}
        assert required <= set(DEFAULT_RISK_PARAMS.keys())

    def test_vol_target_default(self):
        assert DEFAULT_RISK_PARAMS["vol_target"] == 0.15

    def test_vol_clamp_range(self):
        assert DEFAULT_RISK_PARAMS["vol_target_min"] == 0.5
        assert DEFAULT_RISK_PARAMS["vol_target_max"] == 2.0

    def test_vol_lookback(self):
        assert DEFAULT_RISK_PARAMS["vol_lookback"] == 20
