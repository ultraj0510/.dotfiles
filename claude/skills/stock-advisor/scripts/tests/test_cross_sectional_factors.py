import pytest
from factor_engine import compute_cross_sectional_factors


class TestCrossSectionalFactors:
    def test_small_universe_fallback(self):
        result = compute_cross_sectional_factors(["7203.T"])
        assert result["universe_size"] == 1
        assert "cross_sectional_universe_too_small" in result["warnings"]

    def test_small_universe_two_tickers(self):
        result = compute_cross_sectional_factors(["7203.T", "7974.T"])
        assert "cross_sectional_universe_too_small" in result["warnings"]

    def test_universe_three_returns_ranked(self):
        result = compute_cross_sectional_factors(["7203.T", "7974.T", "8306.T"])
        assert result["universe_size"] == 3
        assert len(result["ranked"]) >= 1
        # Ranks should be assigned
        for r in result["ranked"]:
            assert "composite_rank" in r
            assert "composite_percentile" in r
            assert "factor_scores" in r

    def test_ranks_are_deterministic(self):
        tickers = ["7203.T", "7974.T", "8306.T"]
        r1 = compute_cross_sectional_factors(tickers)
        r2 = compute_cross_sectional_factors(tickers)
        # Same input should produce same ranks
        ranks1 = [r["composite_rank"] for r in r1["ranked"]]
        ranks2 = [r["composite_rank"] for r in r2["ranked"]]
        assert ranks1 == ranks2
