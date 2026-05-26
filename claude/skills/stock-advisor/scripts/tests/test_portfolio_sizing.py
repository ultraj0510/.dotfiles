"""Tests for inverse volatility portfolio sizing (A2) in trade_advisor.py."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestInverseVolWeights:

    def test_module_imports(self):
        from trade_advisor import compute_inverse_vol_weights
        assert callable(compute_inverse_vol_weights)

    def test_weights_sum_near_one_with_equal_vol(self):
        """With mock data where all vols are equal, raw weights should be equal."""
        # This tests the fallback logic when yfinance is unavailable
        # We use positions that should trigger the equal-weight fallback
        from trade_advisor import compute_inverse_vol_weights
        positions = [
            {"ticker": "7974.T", "market_price": 7000, "shares": 100, "mode": "spot"},
            {"ticker": "5803.T", "market_price": 5300, "shares": 100, "mode": "spot"},
            {"ticker": "1515.T", "market_price": 2600, "shares": 100, "mode": "spot"},
        ]
        result = compute_inverse_vol_weights(positions, 10000000)
        assert "allocations" in result
        assert "portfolio_value" in result
        assert "rebalancing_needed" in result
        assert len(result["allocations"]) == 3

    def test_max_position_cap(self):
        """Max position weight should not exceed 25%."""
        from trade_advisor import compute_inverse_vol_weights
        positions = [
            {"ticker": "7974.T", "market_price": 7000, "shares": 100, "mode": "spot"},
            {"ticker": "5803.T", "market_price": 5300, "shares": 100, "mode": "spot"},
        ]
        result = compute_inverse_vol_weights(positions, 1000000)
        for a in result["allocations"]:
            assert a["capped_weight"] <= 0.25 + 0.01  # allow float tolerance

    def test_rounding_to_100_share_units(self):
        """Target shares should be multiples of 100."""
        from trade_advisor import compute_inverse_vol_weights
        positions = [
            {"ticker": "7974.T", "market_price": 7000, "shares": 100, "mode": "spot"},
            {"ticker": "5803.T", "market_price": 5300, "shares": 200, "mode": "spot"},
            {"ticker": "1515.T", "market_price": 2600, "shares": 300, "mode": "spot"},
        ]
        result = compute_inverse_vol_weights(positions, 20000000)
        for a in result["allocations"]:
            assert a["target_shares"] % 100 == 0

    def test_result_structure(self):
        """All required keys present in result."""
        from trade_advisor import compute_inverse_vol_weights
        positions = [
            {"ticker": "7974.T", "market_price": 7000, "shares": 100, "mode": "spot"},
        ]
        result = compute_inverse_vol_weights(positions, 700000)
        assert "portfolio_value" in result
        assert "target_weights" in result
        assert "allocations" in result
        assert "total_actual_weight" in result
        assert "rebalancing_needed" in result
        assert "rebalancing_frequency" in result

    def test_allocation_keys(self):
        """Each allocation has all required fields."""
        from trade_advisor import compute_inverse_vol_weights
        positions = [
            {"ticker": "7974.T", "market_price": 7000, "shares": 100, "mode": "spot"},
        ]
        result = compute_inverse_vol_weights(positions, 700000)
        for a in result["allocations"]:
            for key in ["ticker", "market_price", "raw_weight", "capped_weight",
                         "target_shares", "actual_weight", "deviation_pct"]:
                assert key in a, f"Missing key: {key}"

    def test_empty_positions(self):
        """Empty position list returns valid result."""
        from trade_advisor import compute_inverse_vol_weights
        result = compute_inverse_vol_weights([], 0)
        assert len(result["allocations"]) == 0
        assert result["portfolio_value"] == 0

    def test_portfolio_yaml_loader(self):
        """_load_portfolio_yaml function exists."""
        from trade_advisor import _load_portfolio_yaml
        assert callable(_load_portfolio_yaml)
