import copy
import json
import tempfile
from pathlib import Path
import pytest
from analysis_v2_adapter import read_analysis_v2

VALID_V2 = {
    "schema_version": "2.0",
    "ticker": "5803",
    "as_of": "2026-06-30T08:00:00+09:00",
    "technical": {
        "signal_raw": "HOLD_BUY", "direction": "BUY", "score": 22,
        "trend_state": "strong_uptrend", "indicators": {}, "signals": [], "backtest": {},
    },
    "fundamental": {
        "rating": "HOLD",
        "confidence": {"score": 54, "level": "Medium"},
        "expected_return_pct": -6.3,
        "scenarios": [{"label": "強気", "eps": 150, "per": 50, "price": 7500, "probability": 0.3}],
        "investment_thesis": "テスト判断",
        "analyst_reports": {},
        "catalysts": ["テスト"],
        "disconfirmers": [],
        "monitoring_triggers": [],
    },
    "integrated": {
        "investment_rating": "HOLD", "execution_posture": "NO_TRADE",
        "reasoning": "テスト理由", "risk_flags": ["position_over_cap_watch"],
    },
    "source_run_ids": {},
}

def test_read_analysis_v2_returns_required_keys():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(VALID_V2, f)
        path = Path(f.name)
    try:
        result = read_analysis_v2(path)
        assert result["ticker"] == "5803"
        assert result["investment_rating"] == "HOLD"
        assert result["execution_posture"] == "NO_TRADE"
        assert result["reasoning"] == "テスト理由"
        assert result["fundamental_rating"] == "HOLD"
        assert result["technical_direction"] == "BUY"
        assert "position_over_cap_watch" in result["risk_flags"]
    finally:
        path.unlink()

def test_read_analysis_v2_rejects_v1_schema():
    v1 = {"schema_version": "1.0", "ticker": "5803"}
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(v1, f)
        path = Path(f.name)
    try:
        with pytest.raises(ValueError, match="schema_version"):
            read_analysis_v2(path)
    finally:
        path.unlink()

def test_read_analysis_v2_rejects_missing_key():
    invalid = copy.deepcopy(VALID_V2)
    del invalid["integrated"]["investment_rating"]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(invalid, f)
        path = Path(f.name)
    try:
        with pytest.raises(ValueError, match="investment_rating"):
            read_analysis_v2(path)
    finally:
        path.unlink()

def test_read_analysis_v2_handles_minimal_data():
    minimal = {
        "schema_version": "2.0", "ticker": "9999",
        "technical": {"direction": "HOLD", "signal_raw": "HOLD", "indicators": {}, "signals": [], "backtest": {}},
        "fundamental": {"rating": "HOLD", "scenarios": [], "investment_thesis": "", "catalysts": [], "monitoring_triggers": []},
        "integrated": {"investment_rating": "HOLD", "execution_posture": "NO_TRADE", "reasoning": "", "risk_flags": []},
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(minimal, f)
        path = Path(f.name)
    try:
        result = read_analysis_v2(path)
        assert result["ticker"] == "9999"
        assert result["scenarios"] == []
    finally:
        path.unlink()
