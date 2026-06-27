import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from llm_analyzer import run_llm_analysis, validate_analysis_output, _build_prompt

MOCK_EVIDENCE_PACK = {
    "ticker": "285A",
    "company_name": "キオクシアHD",
    "as_of": "2026-06-26",
    "evidence": [
        {
            "evidence_id": "price-2026-06-26-close",
            "kind": "market_data",
            "field": "close",
            "value": 92180.0,
            "unit": "JPY",
            "source_ref": "daily:2026-06-26",
            "usable": True,
            "period_end": "2026-06-26",
        },
        {
            "evidence_id": "info-profile-sector",
            "kind": "fundamentals",
            "field": "sector",
            "value": "電気機器",
            "source_ref": "company_profile:sector",
            "usable": True,
        },
    ],
    "data_quality": {},
}

MOCK_METRICS: dict = {
    "returns": {},
    "moving_averages": {},
    "rsi": {},
    "macd": {},
    "bollinger": {},
    "volatility": {},
    "volume": {},
}


def test_validate_analysis_output_rejects_missing_sections():
    with pytest.raises(ValueError, match="analyst_reports"):
        validate_analysis_output({})


def test_validate_analysis_output_rejects_wrong_scenario_count():
    with pytest.raises(ValueError, match="3 scenarios"):
        validate_analysis_output({
            "analyst_reports": {"bull_researcher": {}, "bear_researcher": {}},
            "debate": {},
            "portfolio_manager": {
                "scenarios": [
                    {"label": "x", "eps": 1, "per": 1, "probability": 1.0},
                ],
            },
        })


def test_validate_analysis_output_rejects_missing_investment_thesis():
    with pytest.raises(ValueError, match="investment_thesis_ja"):
        validate_analysis_output({
            "analyst_reports": {"bull_researcher": {}, "bear_researcher": {}},
            "debate": {},
            "portfolio_manager": {
                "proposed_rating": "HOLD",
                "scenarios": [
                    {"label": "a", "eps": 1, "per": 1, "probability": 0.3},
                    {"label": "b", "eps": 1, "per": 1, "probability": 0.5},
                    {"label": "c", "eps": 1, "per": 1, "probability": 0.2},
                ],
                # investment_thesis_ja missing
            },
        })


def test_validate_analysis_output_rejects_probability_sum_not_1():
    with pytest.raises(ValueError, match="sum to 1"):
        validate_analysis_output({
            "analyst_reports": {"bull_researcher": {}, "bear_researcher": {}},
            "debate": {},
            "portfolio_manager": {
                "investment_thesis_ja": "test",
                "scenarios": [
                    {"label": "a", "eps": 1, "per": 1, "probability": 0.5},
                    {"label": "b", "eps": 1, "per": 1, "probability": 0.4},
                    {"label": "c", "eps": 1, "per": 1, "probability": 0.3},
                ],
            },
        })


def test_validate_analysis_output_accepts_valid_output():
    result = validate_analysis_output({
        "analyst_reports": {"bull_researcher": {}, "bear_researcher": {}},
        "debate": {},
        "portfolio_manager": {
            "proposed_rating": "HOLD",
            "investment_thesis_ja": "テスト判断サマリー",
            "scenarios": [
                {"label": "強気", "eps": 100, "per": 10, "probability": 0.3},
                {"label": "中立", "eps": 80, "per": 8, "probability": 0.5},
                {"label": "弱気", "eps": 50, "per": 6, "probability": 0.2},
            ],
        },
    })
    assert result is True


def test_run_llm_analysis_returns_completed_on_success():
    mock_provider = MagicMock()
    mock_provider.analyze.return_value = {
        "status": "completed",
        "result": {
            "analyst_reports": {"bull_researcher": {}, "bear_researcher": {}},
            "debate": {},
            "portfolio_manager": {
                "proposed_rating": "BUY",
                "investment_thesis_ja": "テスト判断",
                "scenarios": [
                    {"label": "強気", "eps": 100, "per": 10, "probability": 0.3},
                    {"label": "中立", "eps": 80, "per": 8, "probability": 0.5},
                    {"label": "弱気", "eps": 50, "per": 6, "probability": 0.2},
                ],
            },
        },
    }

    with tempfile.TemporaryDirectory() as tmp:
        ep_path = Path(tmp) / "evidence-pack.json"
        mm_path = Path(tmp) / "market-metrics.json"
        ep_path.write_text(json.dumps(MOCK_EVIDENCE_PACK))
        mm_path.write_text(json.dumps(MOCK_METRICS))
        run_dir = Path(tmp) / "run"
        run_dir.mkdir()

        result = run_llm_analysis(ep_path, mm_path, run_dir, mock_provider)

    assert result["status"] == "completed"


def test_run_llm_analysis_saves_llm_result_to_run_dir():
    mock_provider = MagicMock()
    mock_provider.analyze.return_value = {
        "status": "completed",
        "result": {
            "analyst_reports": {"bull_researcher": {}, "bear_researcher": {}},
            "debate": {},
            "portfolio_manager": {
                "proposed_rating": "HOLD",
                "investment_thesis_ja": "テスト判断",
                "scenarios": [
                    {"label": "強気", "eps": 100, "per": 10, "probability": 0.3},
                    {"label": "中立", "eps": 80, "per": 8, "probability": 0.5},
                    {"label": "弱気", "eps": 50, "per": 6, "probability": 0.2},
                ],
            },
        },
    }

    with tempfile.TemporaryDirectory() as tmp:
        ep_path = Path(tmp) / "evidence-pack.json"
        mm_path = Path(tmp) / "market-metrics.json"
        ep_path.write_text(json.dumps(MOCK_EVIDENCE_PACK))
        mm_path.write_text(json.dumps(MOCK_METRICS))
        run_dir = Path(tmp) / "run"
        run_dir.mkdir()

        run_llm_analysis(ep_path, mm_path, run_dir, mock_provider)

        assert (run_dir / "llm-analysis-result.json").exists()
        saved = json.loads((run_dir / "llm-analysis-result.json").read_text())
        assert saved["portfolio_manager"]["proposed_rating"] == "HOLD"


def test_build_prompt_includes_company_name():
    prompt = _build_prompt("テスト株式会社", "9999", "2026-01-01", {})
    assert "テスト株式会社" in prompt
    assert "9999" in prompt


def test_file_provider_reads_valid_json(tmp_path):
    from llm_provider import FileProvider

    result_file = tmp_path / "result.json"
    result_file.write_text(json.dumps({
        "analyst_reports": {"bull_researcher": {}, "bear_researcher": {}},
        "debate": {},
        "portfolio_manager": {
            "proposed_rating": "HOLD",
            "investment_thesis_ja": "テスト判断",
            "scenarios": [
                {"label": "強気", "eps": 100, "per": 10, "probability": 0.3},
                {"label": "中立", "eps": 80, "per": 8, "probability": 0.5},
                {"label": "弱気", "eps": 50, "per": 6, "probability": 0.2},
            ],
        },
    }))

    p = FileProvider(result_path=result_file)
    result = p.analyze(
        prompt="", schema={}, context={},
        evidence_pack={}, market_metrics={},
        company_name="", ticker="", run_dir=tmp_path,
    )
    assert result["status"] == "completed"


def test_file_provider_rejects_missing_file(tmp_path):
    from llm_provider import FileProvider

    p = FileProvider(result_path=tmp_path / "nonexistent.json")
    result = p.analyze(
        prompt="", schema={}, context={},
        evidence_pack={}, market_metrics={},
        company_name="", ticker="", run_dir=tmp_path,
    )
    assert result["status"] == "failed"
