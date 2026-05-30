import pytest
from signal_reliability import (
    shrink_win_probability,
    expected_value_after_cost_pct,
    reliability_vetoes,
)


class TestShrinkWinProbability:
    def test_perfect_record_shrinks_below_100(self):
        p = shrink_win_probability(wins=4, losses=0)
        assert 0.5 < p < 1.0

    def test_zero_wins_shrinks_above_zero(self):
        p = shrink_win_probability(wins=0, losses=4)
        assert 0.0 < p < 0.5

    def test_no_samples_returns_prior(self):
        assert shrink_win_probability(wins=0, losses=0) == 0.5

    def test_large_sample_approaches_raw(self):
        p = shrink_win_probability(wins=80, losses=20)
        assert abs(p - 0.80) < 0.05


class TestExpectedValue:
    def test_positive_ev(self):
        ev = expected_value_after_cost_pct(
            p_win=0.6, avg_win_pct=5.0, avg_loss_pct=-3.0, round_trip_cost_pct=0.5,
        )
        assert ev > 0

    def test_costs_dominate_negative_ev(self):
        ev = expected_value_after_cost_pct(
            p_win=0.55, avg_win_pct=2.0, avg_loss_pct=-2.0, round_trip_cost_pct=0.5,
        )
        assert ev < 0

    def test_always_lose_negative_ev(self):
        ev = expected_value_after_cost_pct(
            p_win=0.0, avg_win_pct=0.0, avg_loss_pct=-3.0, round_trip_cost_pct=0.5,
        )
        assert ev < 0


class TestReliabilityVetoes:
    def test_low_sample(self):
        v = reliability_vetoes(sample_count=3, p_win_shrunk=0.6, ev_after_cost_pct=2.0)
        assert "low_sample" in v

    def test_negative_ev(self):
        v = reliability_vetoes(sample_count=20, p_win_shrunk=0.6, ev_after_cost_pct=-1.0)
        assert "negative_ev" in v

    def test_negative_walk_forward(self):
        v = reliability_vetoes(sample_count=20, p_win_shrunk=0.6, ev_after_cost_pct=2.0,
                               walk_forward={"sharpe_is": 0.8, "sharpe_oos": -0.2})
        assert "negative_walk_forward" in v

    def test_overfit_walk_forward(self):
        v = reliability_vetoes(sample_count=20, p_win_shrunk=0.6, ev_after_cost_pct=2.0,
                               walk_forward={"sharpe_is": 2.0, "sharpe_oos": 0.5})
        assert "overfit_walk_forward" in v

    def test_no_vetoes_when_clean(self):
        v = reliability_vetoes(sample_count=20, p_win_shrunk=0.6, ev_after_cost_pct=2.0,
                               walk_forward={"sharpe_is": 0.8, "sharpe_oos": 0.7})
        assert len(v) == 0
