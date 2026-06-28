from portfolio_helper import merge_portfolio_context, check_credit_expiry

from datetime import date, timedelta


MOCK_PORTFOLIO = {
    "account": {
        "total_assets": 18000000, "available_cash": 1800000,
        "margin_ratio": 35.58, "buying_power": 1780000, "margin_principal": 33225000,
    },
    "holdings": [
        {"ticker": "5803.T", "name": "フジクラ", "position_type": "現物",
         "account_type": "特定", "quantity": 700, "cost_price": 4982, "current_price": 6131},
        {"ticker": "285A.T", "name": "キオクシアHD", "position_type": "信用",
         "margin_side": "買建", "quantity": 300, "cost_price": 110750, "current_price": 92180,
         "open_date": "2026-06-23", "expiry_date": None},
    ],
}

MOCK_ANALYSIS = {
    "ticker": "5803", "investment_rating": "HOLD", "execution_posture": "NO_TRADE",
    "reasoning": "テスト", "risk_flags": [],
    "fundamental_rating": "HOLD", "technical_direction": "BUY",
    "technical_signal_raw": "HOLD_BUY", "scenarios": [],
    "investment_thesis": "テスト", "catalysts": ["テスト"], "monitoring_triggers": [],
}


class TestMergePortfolioContext:
    def test_adds_holdings(self):
        result = merge_portfolio_context(MOCK_PORTFOLIO, MOCK_ANALYSIS)
        assert "holdings" in result
        assert len(result["holdings"]) == 1  # only 5803 matches
        assert result["holdings"][0]["quantity"] == 700
        assert result["holdings"][0]["pnl_pct"] > 0
        assert result["holdings"][0]["name"] == "フジクラ"

    def test_computes_weight(self):
        result = merge_portfolio_context(MOCK_PORTFOLIO, MOCK_ANALYSIS)
        w = result["holdings"][0]["weight_pct"]
        assert 20 < w < 30  # 700*6131/18000000 ≈ 23.8%

    def test_preserves_analysis(self):
        result = merge_portfolio_context(MOCK_PORTFOLIO, MOCK_ANALYSIS)
        # analysis should preserve all original keys (risk_flags may be augmented)
        for key in ("ticker", "investment_rating", "execution_posture",
                     "fundamental_rating", "technical_direction"):
            assert result["analysis"][key] == MOCK_ANALYSIS[key]

    def test_default_today_action(self):
        result = merge_portfolio_context(MOCK_PORTFOLIO, MOCK_ANALYSIS)
        assert result["today_action"] == "NO_TRADE"
        assert result["overridden"] is False

    def test_overrides_on_low_margin(self):
        low_margin = dict(MOCK_PORTFOLIO)
        low_margin["account"] = dict(MOCK_PORTFOLIO["account"])
        low_margin["account"]["margin_ratio"] = 25.0
        result = merge_portfolio_context(low_margin, MOCK_ANALYSIS)
        assert result["today_action"] == "REDUCE"
        assert result["overridden"] is True
        assert "保証金率" in result["override_reason"]

    def test_overrides_on_credit_expiry(self):
        """Override to REDUCE when a matching holding has urgent credit expiry."""
        from copy import deepcopy
        port = deepcopy(MOCK_PORTFOLIO)
        soon = (date.today() + timedelta(days=20)).isoformat()
        # Add a matching credit holding with near expiry
        port["holdings"].append({
            "ticker": "5803.T", "name": "フジクラ", "position_type": "信用",
            "margin_side": "買建", "quantity": 100, "cost_price": 5000,
            "current_price": 6131, "open_date": "2026-06-01",
            "expiry_date": soon,
        })
        result = merge_portfolio_context(port, MOCK_ANALYSIS)
        assert result["today_action"] == "REDUCE"
        assert result["overridden"] is True
        assert "信用期限" in result["override_reason"]

    def test_position_over_cap_watch(self):
        """Sets risk_flag when any holding exceeds 20% weight."""
        from copy import deepcopy
        port = deepcopy(MOCK_PORTFOLIO)
        # Give holding much higher weight
        port["holdings"][0]["current_price"] = 600000
        port["holdings"][0]["quantity"] = 10
        result = merge_portfolio_context(port, MOCK_ANALYSIS)
        assert "position_over_cap_watch" in result.get("risk_flags", [])

    def test_no_risk_flag_when_under_cap(self):
        """No risk_flag set when weight is <= 20%."""
        from copy import deepcopy
        port = deepcopy(MOCK_PORTFOLIO)
        # Reduce holding so weight falls under 20%
        port["holdings"][0]["quantity"] = 500
        port["holdings"][0]["current_price"] = 5000
        # 500 * 5000 / 18000000 ≈ 13.9%
        result = merge_portfolio_context(port, MOCK_ANALYSIS)
        flags = result.get("risk_flags", [])
        assert "position_over_cap_watch" not in flags

    def test_merge_keeps_original_portfolio_untouched(self):
        """The function should not mutate the input dicts."""
        from copy import deepcopy
        port_copy = deepcopy(MOCK_PORTFOLIO)
        analysis_copy = deepcopy(MOCK_ANALYSIS)
        merge_portfolio_context(MOCK_PORTFOLIO, MOCK_ANALYSIS)
        assert MOCK_PORTFOLIO == port_copy
        assert MOCK_ANALYSIS == analysis_copy

    def test_no_matching_holding(self):
        """Returns holdings=[] and no action override for an unmatched ticker."""
        analysis = dict(MOCK_ANALYSIS, ticker="9999")
        result = merge_portfolio_context(MOCK_PORTFOLIO, analysis)
        assert result["holdings"] == []
        assert result["today_action"] == "NO_TRADE"
        assert result["overridden"] is False

    def test_output_structure(self):
        """Verify the output dict has all expected keys."""
        result = merge_portfolio_context(MOCK_PORTFOLIO, MOCK_ANALYSIS)
        expected_keys = {
            "ticker", "name", "source", "holdings", "analysis", "today_action",
            "overridden", "override_reason", "order_candidates", "triggers",
            "risk_flags",
        }
        assert expected_keys.issubset(result.keys())


class TestCheckCreditExpiry:
    def test_no_expiry(self):
        h = {"position_type": "信用", "expiry_date": None}
        assert check_credit_expiry(h) is False

    def test_not_credit(self):
        h = {"position_type": "現物"}
        assert check_credit_expiry(h) is False

    def test_urgent(self):
        soon = (date.today() + timedelta(days=20)).isoformat()
        h = {"position_type": "信用", "expiry_date": soon}
        assert check_credit_expiry(h) is True

    def test_beyond_threshold(self):
        far = (date.today() + timedelta(days=45)).isoformat()
        h = {"position_type": "信用", "expiry_date": far}
        assert check_credit_expiry(h) is False

    def test_exactly_at_threshold(self):
        exactly = (date.today() + timedelta(days=30)).isoformat()
        h = {"position_type": "信用", "expiry_date": exactly}
        assert check_credit_expiry(h) is True

    def test_invalid_date_string(self):
        h = {"position_type": "信用", "expiry_date": "not-a-date"}
        assert check_credit_expiry(h) is False

    def test_expiry_key_missing(self):
        h = {"position_type": "信用"}
        assert check_credit_expiry(h) is False

    def test_risk_flags_injected_into_analysis(self):
        result = merge_portfolio_context(MOCK_PORTFOLIO, MOCK_ANALYSIS)
        # risk_flags should be in analysis block, not just top-level
        assert "risk_flags" in result["analysis"]
        # top-level should also have risk_flags for convenience
        assert "risk_flags" in result

    def test_source_field_is_holding(self):
        result = merge_portfolio_context(MOCK_PORTFOLIO, MOCK_ANALYSIS)
        assert result["source"] == "holding"


def test_triggers_from_analysis_monitoring():
        ana = dict(MOCK_ANALYSIS)
        ana["monitoring_triggers"] = ["2026-08-06 1Q決算", "月次市況"]
        result = merge_portfolio_context(MOCK_PORTFOLIO, ana)
        assert result["triggers"] == ["2026-08-06 1Q決算", "月次市況"]
