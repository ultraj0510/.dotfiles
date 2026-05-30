import pytest
from quant_schema import QuantDecision


class TestQuantSchema:
    def test_valid_buy_market_order(self):
        d = QuantDecision(ticker="7203.T", action="BUY", order_type="market",
                          target_shares=100, order_shares=100)
        assert d.action == "BUY"

    def test_sell_without_limit_fails(self):
        with pytest.raises(ValueError, match="limit_price"):
            QuantDecision(ticker="7203.T", action="SELL", order_type="limit",
                          target_shares=100, order_shares=100)

    def test_no_trade_with_nonzero_shares_fails(self):
        with pytest.raises(ValueError, match="non-zero"):
            QuantDecision(ticker="7203.T", action="NO_TRADE", order_shares=100)

    def test_unknown_action_fails(self):
        with pytest.raises(ValueError, match="action"):
            QuantDecision(ticker="7203.T", action="UNKNOWN")

    def test_negative_target_shares_fails(self):
        with pytest.raises(ValueError, match="target_shares"):
            QuantDecision(ticker="7203.T", action="BUY", target_shares=-100)

    def test_valid_sell_with_limit(self):
        d = QuantDecision(ticker="7203.T", action="SELL", order_type="limit",
                          limit_price=1500, target_shares=100, order_shares=100)
        assert d.limit_price == 1500

from quant_schema import PositionDecision


class TestPositionDecision:
    def test_position_decision_requires_lot_sized_order(self):
        d = PositionDecision(
            position_id="5803.T:信用:2", ticker="5803.T",
            position_type="信用", action="REDUCE",
            quantity=100, order_shares=100, reason="negative_walk_forward",
        )
        assert d.order_shares == 100

    def test_position_decision_rejects_non_lot_order(self):
        with pytest.raises(ValueError, match="lot"):
            PositionDecision(
                position_id="5803.T:信用:2", ticker="5803.T",
                position_type="信用", action="REDUCE",
                quantity=100, order_shares=50, reason="negative_walk_forward",
            )

    def test_position_decision_rejects_excess_order(self):
        with pytest.raises(ValueError, match="exceed"):
            PositionDecision(
                position_id="5803.T:信用:2", ticker="5803.T",
                position_type="信用", action="REDUCE",
                quantity=100, order_shares=200, reason="negative_walk_forward",
            )
