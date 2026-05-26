"""Tests for transaction cost model (A5) in backtest_engine.py."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest_engine import (
    _compute_transaction_cost,
    DEFAULT_COST_PARAMS,
    TOPIX500_TICKERS,
)


class TestComputeTransactionCost:

    def test_commission_calculation(self):
        tc = _compute_transaction_cost(3000, 100, "1515.T", 1.0)
        expected = 3000 * 100 * 0.001 * 2
        assert tc["commission"] == expected

    def test_slippage_topix500(self):
        tc = _compute_transaction_cost(3000, 100, "7974.T", 1.0)
        expected = 3000 * 100 * 0.0005 * 2
        assert tc["slippage"] == expected

    def test_slippage_other(self):
        tc = _compute_transaction_cost(3000, 100, "1515.T", 1.0)
        expected = 3000 * 100 * 0.0015 * 2
        assert tc["slippage"] == expected

    def test_impact_basic(self):
        tc = _compute_transaction_cost(3000, 100, "7974.T", 1.0)
        assert tc["impact"] == 450.0

    def test_impact_with_high_volume_ratio(self):
        tc = _compute_transaction_cost(3000, 100, "7974.T", 4.0)
        assert tc["impact"] == 900.0

    def test_impact_cap(self):
        tc = _compute_transaction_cost(1000, 100, "1515.T", 100.0)
        cap = 0.02 * 1000 * 100
        assert tc["impact"] <= cap
        assert tc["impact"] == cap

    def test_total_is_sum_of_parts(self):
        tc = _compute_transaction_cost(5000, 100, "7974.T", 1.5)
        assert tc["total"] == tc["commission"] + tc["slippage"] + tc["impact"]

    def test_total_pct(self):
        tc = _compute_transaction_cost(3000, 100, "7974.T", 1.0)
        notional = 3000 * 100
        expected_pct = tc["total"] / notional * 100
        assert abs(tc["total_pct"] - expected_pct) < 0.01

    def test_non_negative_costs(self):
        for vol_ratio in [0.1, 0.5, 1.0, 2.0, 5.0, 50.0]:
            for ticker in ["7974.T", "1515.T"]:
                tc = _compute_transaction_cost(3000, 100, ticker, vol_ratio)
                assert tc["commission"] >= 0
                assert tc["slippage"] >= 0
                assert tc["impact"] >= 0
                assert tc["total"] >= 0

    def test_costs_scale_with_price(self):
        tc_low = _compute_transaction_cost(1000, 100, "7974.T", 1.0)
        tc_high = _compute_transaction_cost(5000, 100, "7974.T", 1.0)
        assert tc_high["commission"] == tc_low["commission"] * 5
        assert tc_high["slippage"] == tc_low["slippage"] * 5

    def test_default_cost_params(self):
        required = {"commission", "slippage_topix500", "slippage_other",
                     "impact_mult_topix500", "impact_mult_other",
                     "impact_cap", "volume_floor"}
        assert required <= set(DEFAULT_COST_PARAMS.keys())
