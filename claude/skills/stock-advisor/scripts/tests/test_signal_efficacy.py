"""Tests for signal efficacy tracker (A4)."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signal_efficacy import (
    _sharpe_from_returns,
    _overall_status,
    track_efficacy,
    MIN_TRADES_FOR_EFFICACY,
    POSITIVE_WINDOWS_FOR_REENABLE,
)


class TestSharpeFromReturns:

    def test_positive_returns(self):
        sr = round(_sharpe_from_returns([0.01, 0.02, 0.01, 0.03, 0.01]), 2)
        assert sr > 0

    def test_negative_returns(self):
        sr = round(_sharpe_from_returns([-0.01, -0.02, -0.01, -0.03, -0.01]), 2)
        assert sr < 0

    def test_zero_returns(self):
        assert _sharpe_from_returns([0.0, 0.0, 0.0]) == 0.0

    def test_single_return(self):
        assert _sharpe_from_returns([0.01]) == 0.0

    def test_empty_returns(self):
        assert _sharpe_from_returns([]) == 0.0


class TestOverallStatus:

    def test_all_active(self):
        rules = {
            "trend_following": {"status": "active", "status_detail": "ok", "total_trades": 10, "rolling_windows": []},
            "momentum_buy": {"status": "active", "status_detail": "ok", "total_trades": 8, "rolling_windows": []},
        }
        result = _overall_status(rules)
        assert result["status"] == "healthy"

    def test_all_degraded(self):
        rules = {
            "trend_following": {"status": "degraded", "status_detail": "bad", "total_trades": 5, "rolling_windows": []},
        }
        result = _overall_status(rules)
        assert result["status"] == "degraded"

    def test_mixed(self):
        rules = {
            "trend_following": {"status": "active", "status_detail": "ok", "total_trades": 10, "rolling_windows": []},
            "momentum_buy": {"status": "degraded", "status_detail": "bad", "total_trades": 10, "rolling_windows": []},
        }
        result = _overall_status(rules)
        assert result["status"] == "mixed"

    def test_all_insufficient(self):
        rules = {
            "trend_following": {"status": "insufficient_data", "status_detail": "low", "total_trades": 2, "rolling_windows": []},
        }
        result = _overall_status(rules)
        assert result["status"] == "insufficient_data"

    def test_empty_rules(self):
        result = _overall_status({})
        assert result["status"] == "insufficient_data"


class TestConstants:

    def test_min_trades_threshold(self):
        assert MIN_TRADES_FOR_EFFICACY == 5

    def test_positive_windows_for_reenable(self):
        assert POSITIVE_WINDOWS_FOR_REENABLE == 2
