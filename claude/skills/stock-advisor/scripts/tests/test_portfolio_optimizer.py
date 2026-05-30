import pytest
from portfolio_optimizer import (
    compute_buy_order_shares,
    compute_sell_order_shares,
    margin_expiry_vetoes,
    position_cap_vetoes,
    floor_to_lot,
    MARGIN_URGENT_DAYS,
    MARGIN_WATCH_DAYS,
)


class TestBuyOrderSizing:
    def test_capped_by_position_limit(self):
        shares, vetoes = compute_buy_order_shares(
            total_assets=10_000_000, available_cash=5_000_000,
            current_position_value=0, entry_price=1000,
            stop_loss=950, atr=20,
        )
        assert shares <= 2000  # 20% of 10M at 1000/sh = 2000

    def test_capped_by_risk_budget(self):
        shares, _ = compute_buy_order_shares(
            total_assets=10_000_000, available_cash=5_000_000,
            current_position_value=0, entry_price=1000,
            stop_loss=900, atr=20,
        )
        risk_budget = 10_000_000 * 0.02  # 200k
        per_share_risk = 100
        expected_max = risk_budget / per_share_risk  # 2000
        assert shares <= expected_max

    def test_capped_by_available_cash(self):
        shares, _ = compute_buy_order_shares(
            total_assets=10_000_000, available_cash=50_000,
            current_position_value=0, entry_price=1000,
            stop_loss=950, atr=20,
        )
        assert shares <= 50

    def test_correlation_halves_size(self):
        shares, vetoes = compute_buy_order_shares(
            total_assets=10_000_000, available_cash=5_000_000,
            current_position_value=0, entry_price=1000,
            stop_loss=950, atr=20, correlation_concentration=True,
        )
        shares_no_corr, _ = compute_buy_order_shares(
            total_assets=10_000_000, available_cash=5_000_000,
            current_position_value=0, entry_price=1000,
            stop_loss=950, atr=20, correlation_concentration=False,
        )
        assert shares <= shares_no_corr // 2 + 100
        assert "correlation_concentration" in vetoes


class TestSellOrderSizing:
    def test_never_exceeds_current_shares(self):
        assert compute_sell_order_shares(current_shares=300, recommended_reduce_shares=500) == 300

    def test_negative_reduce_returns_zero(self):
        assert compute_sell_order_shares(current_shares=300, recommended_reduce_shares=-100) == 0


class TestMarginExpiry:
    def test_no_expiry_returns_empty(self):
        assert margin_expiry_vetoes(None) == []

    def test_future_expiry_no_veto(self):
        from datetime import date as dt_date, timedelta
        far = (dt_date.today() + timedelta(days=MARGIN_WATCH_DAYS + 10)).isoformat()
        assert margin_expiry_vetoes(far) == []


class TestFloorToLot:
    def test_floor_to_lot(self):
        assert floor_to_lot(250) == 200
        assert floor_to_lot(99) == 0
        assert floor_to_lot(100) == 100
