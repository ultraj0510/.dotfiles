"""Tests for orchestrator Phase 4 branching, fallback, and manifest."""
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orchestrator import _run_phase4


def _make_evidence_pack():
    return json.dumps({
        "ticker": "285A", "company_name": "キオクシアHD",
        "as_of": "2026-06-28",
        "evidence": [
            {"evidence_id": "p-close", "kind": "market_data", "field": "close",
             "value": 92180.0, "source_ref": "daily:2026-06-28", "usable": True,
             "period_end": "2026-06-28"},
        ],
        "data_quality": {},
    })


def _make_market_metrics():
    return json.dumps({
        "returns": {}, "moving_averages": {}, "rsi": {}, "macd": {},
        "bollinger": {}, "volatility": {}, "volume": {},
    })


def _make_valid_phase4_result():
    return {
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
                "catalysts": [], "disconfirmers": [],
                "monitoring_triggers": [], "data_gaps": [],
            },
        },
        "provider": "file",
        "model": "file",
        "elapsed_seconds": 0.0,
    }


def test_file_provider_requires_llm_result(tmp_path):
    """file provider without --llm-result returns failed."""
    ep = tmp_path / "evidence-pack.json"
    mm = tmp_path / "market-metrics.json"
    ep.write_text(_make_evidence_pack())
    mm.write_text(_make_market_metrics())
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = _run_phase4(
        provider_name="file",
        pack_path=ep,
        market_metrics_path=mm,
        run_dir=run_dir,
        llm_result=None,
    )
    assert result["status"] == "failed"
    assert "llm-result" in result.get("error", "")


def test_file_provider_succeeds_with_valid_result(tmp_path):
    """file provider with valid --llm-result returns completed."""
    ep = tmp_path / "evidence-pack.json"
    mm = tmp_path / "market-metrics.json"
    result_json = tmp_path / "phase4.json"
    ep.write_text(_make_evidence_pack())
    mm.write_text(_make_market_metrics())
    result_json.write_text(json.dumps(_make_valid_phase4_result()["result"]))
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = _run_phase4(
        provider_name="file",
        pack_path=ep,
        market_metrics_path=mm,
        run_dir=run_dir,
        llm_result=result_json,
    )
    assert result["status"] == "completed"


def test_tradingagents_fallback_to_file(tmp_path):
    """tradingagents fails → fallback to file succeeds."""
    from tradingagents_bridge import run_analysis as ta_run

    ep = tmp_path / "evidence-pack.json"
    mm = tmp_path / "market-metrics.json"
    result_json = tmp_path / "phase4.json"
    ep.write_text(_make_evidence_pack())
    mm.write_text(_make_market_metrics())
    result_json.write_text(json.dumps(_make_valid_phase4_result()["result"]))
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    # tradingagents will fail (not installed), fallback to file
    with patch("orchestrator._run_phase4") as mock_run:
        # We test _execute directly via the internal function
        pass

    # Actually test: _run_phase4 calls _execute for tradingagents (fails), then file (succeeds)
    mock_ta = MagicMock()
    mock_ta.return_value = {"status": "failed", "error": "TradingAgents not installed"}

    with patch("tradingagents_bridge.run_analysis", mock_ta):
        result = _run_phase4(
            provider_name="tradingagents",
            pack_path=ep,
            market_metrics_path=mm,
            run_dir=run_dir,
            fallback_provider_name="file",
            llm_result=result_json,
        )

    assert result["status"] == "completed"
    assert result["fallback_from"] == "tradingagents"
    assert "TradingAgents" in result.get("fallback_error", "")


def test_fallback_only_for_tradingagents(tmp_path):
    """fallback is ignored when primary is not tradingagents."""
    ep = tmp_path / "evidence-pack.json"
    mm = tmp_path / "market-metrics.json"
    result_json = tmp_path / "phase4.json"
    ep.write_text(_make_evidence_pack())
    mm.write_text(_make_market_metrics())
    result_json.write_text(json.dumps(_make_valid_phase4_result()["result"]))
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    # file provider succeeds, fallback should not trigger
    result = _run_phase4(
        provider_name="file",
        pack_path=ep,
        market_metrics_path=mm,
        run_dir=run_dir,
        llm_result=result_json,
        fallback_provider_name="anthropic",  # should be ignored
    )
    assert result["status"] == "completed"
    assert "fallback_from" not in result


def test_validation_failure_returns_failed(tmp_path):
    """Phase 4 result with missing investment_thesis_ja → failed."""
    from llm_analyzer import run_llm_analysis
    from llm_provider import FileProvider

    ep = tmp_path / "evidence-pack.json"
    mm = tmp_path / "market-metrics.json"
    result_json = tmp_path / "phase4.json"
    ep.write_text(_make_evidence_pack())
    mm.write_text(_make_market_metrics())
    # Missing investment_thesis_ja
    result_json.write_text(json.dumps({
        "analyst_reports": {"bull_researcher": {}, "bear_researcher": {}},
        "debate": {},
        "portfolio_manager": {
            "proposed_rating": "HOLD",
            "scenarios": [
                {"label": "強気", "eps": 100, "per": 10, "probability": 0.3},
                {"label": "中立", "eps": 80, "per": 8, "probability": 0.5},
                {"label": "弱気", "eps": 50, "per": 6, "probability": 0.2},
            ],
        },
    }))
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    provider = FileProvider(result_path=result_json)
    result = run_llm_analysis(ep, mm, run_dir, provider)

    assert result["status"] == "failed"
    assert "investment_thesis_ja" in result.get("error", "")
