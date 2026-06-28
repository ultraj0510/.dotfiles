import pytest
from price_forecast import build_price_forecast, validate_forecast_guardrails

MOCK_TECHNICAL = {
    "direction": "BUY",
    "trend_state": "strong_uptrend",
    "indicators": {
        "close": 6131,
        "atr": 491,
        "rsi": 60.4,
        "bollinger": {"position_pct": 85.4},
    },
    "signals": [{"type": "BUY", "rule": "trend_following", "strength": "moderate"}],
}

MOCK_FUNDAMENTAL = {
    "rating": "HOLD",
    "scenarios": [],
    "catalysts": ["2026-08-06 1Q決算"],
    "monitoring_triggers": [],
}

MOCK_INTEGRATED = {
    "investment_rating": "HOLD",
    "execution_posture": "NO_TRADE",
    "risk_flags": [],
}

MOCK_MARKET_METRICS = {
    "topix_relative": "outperform",
}

MOCK_LLM_RESULT = {
    "result": {
        "portfolio_manager": {
            "investment_thesis_ja": "テスト判断",
            "scenarios": [],
        },
    },
}


def test_build_price_forecast_returns_required_keys():
    result = build_price_forecast(
        ticker="5803",
        as_of="2026-07-01T08:00:00+09:00",
        technical=MOCK_TECHNICAL,
        fundamental=MOCK_FUNDAMENTAL,
        integrated=MOCK_INTEGRATED,
        market_metrics=MOCK_MARKET_METRICS,
        llm_result=MOCK_LLM_RESULT,
    )
    assert result["base_price"] == 6131
    assert result["ohlc"]["high"] >= result["ohlc"]["open"]
    assert result["ohlc"]["low"] <= result["ohlc"]["close"]
    assert result["confidence"] in ("medium", "low")
    assert "reasoning" in result


def test_forecast_guardrails_high_above_max():
    ohlc = {"open": 6000, "high": 5900, "low": 5800, "close": 5850}
    ok, reason = validate_forecast_guardrails(ohlc, base_price=6000, atr=500)
    assert not ok
    assert "high" in reason.lower()


def test_forecast_guardrails_low_above_min():
    ohlc = {"open": 6000, "high": 6500, "low": 6100, "close": 6200}
    ok, reason = validate_forecast_guardrails(ohlc, base_price=6000, atr=500)
    assert not ok
    assert "low" in reason.lower()


def test_forecast_guardrails_range_too_wide():
    ohlc = {"open": 6000, "high": 8500, "low": 5500, "close": 6200}
    ok, reason = validate_forecast_guardrails(ohlc, base_price=6000, atr=500)
    assert not ok
    assert "4" in reason


def test_forecast_guardrails_valid():
    ohlc = {"open": 6149, "high": 6710, "low": 5915, "close": 6250}
    ok, reason = validate_forecast_guardrails(ohlc, base_price=6131, atr=491)
    assert ok


def test_forecast_unavailable_when_missing_atr():
    tech_no_atr = dict(MOCK_TECHNICAL)
    tech_no_atr["indicators"] = {"close": 6131}
    result = build_price_forecast(
        ticker="5803", as_of="2026-07-01T08:00:00+09:00",
        technical=tech_no_atr,
        fundamental=MOCK_FUNDAMENTAL, integrated=MOCK_INTEGRATED,
        market_metrics=MOCK_MARKET_METRICS, llm_result=MOCK_LLM_RESULT,
    )
    assert result["confidence"] == "unavailable"
    assert result["unavailable_reason"] == "missing_atr"
    assert result["ohlc"] is None


def test_forecast_guardrail_violation_returns_unavailable():
    """Guardrail violations return unavailable, not just low confidence."""
    # Inject a technical state that will produce an invalid OHLC
    bad_tech = dict(MOCK_TECHNICAL)
    bad_tech["indicators"] = {"close": 6131, "atr": 10}  # tiny ATR → wide range
    bad_tech["trend_state"] = "strong_uptrend"
    result = build_price_forecast(
        ticker="5803", as_of="2026-07-01T08:00:00+09:00",
        technical=bad_tech,
        fundamental=MOCK_FUNDAMENTAL, integrated=MOCK_INTEGRATED,
        market_metrics=MOCK_MARKET_METRICS, llm_result=MOCK_LLM_RESULT,
    )
    assert result["confidence"] == "unavailable"
    assert "guardrail" in (result.get("unavailable_reason") or "")


def test_forecast_unavailable_when_missing_close():
    tech_no_close = dict(MOCK_TECHNICAL)
    tech_no_close["indicators"] = {"atr": 491}
    result = build_price_forecast(
        ticker="5803", as_of="2026-07-01T08:00:00+09:00",
        technical=tech_no_close,
        fundamental=MOCK_FUNDAMENTAL, integrated=MOCK_INTEGRATED,
        market_metrics=MOCK_MARKET_METRICS, llm_result=MOCK_LLM_RESULT,
    )
    assert result["confidence"] == "unavailable"
