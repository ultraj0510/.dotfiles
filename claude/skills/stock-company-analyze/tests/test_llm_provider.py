import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_get_provider_anthropic():
    from llm_provider import get_provider

    p = get_provider("anthropic")
    assert p.provider_name == "anthropic"


def test_get_provider_file():
    from llm_provider import get_provider, FileProvider

    p = get_provider("file", result_path=Path("/tmp/test.json"))
    assert isinstance(p, FileProvider)
    assert p.provider_name == "file"


def test_get_provider_file_requires_result_path():
    from llm_provider import get_provider

    with pytest.raises(ValueError, match="result_path"):
        get_provider("file")


def test_get_provider_codex_not_implemented():
    from llm_provider import get_provider

    p = get_provider("codex")
    assert p.provider_name == "codex"
    with pytest.raises(NotImplementedError):
        p.analyze(
            prompt="",
            schema={},
            context={},
            evidence_pack={},
            market_metrics={},
            company_name="",
            ticker="",
            run_dir=Path("/tmp"),
        )


def test_get_provider_unknown():
    from llm_provider import get_provider

    with pytest.raises(ValueError, match="Unknown provider"):
        get_provider("unknown")


def test_provider_is_abstract():
    from llm_provider import LLMProvider

    with pytest.raises(TypeError):
        LLMProvider()


def test_anthropic_provider_model_default():
    from llm_provider import AnthropicProvider

    p = AnthropicProvider()
    assert p.model == "claude-sonnet-4-6"


def test_anthropic_provider_model_custom():
    from llm_provider import AnthropicProvider

    p = AnthropicProvider(model="claude-opus-4-8")
    assert p.model == "claude-opus-4-8"


@patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
def test_anthropic_analyze_returns_structured_result():
    from llm_provider import AnthropicProvider

    mock_content = MagicMock()
    mock_content.text = json.dumps({
        "analyst_reports": {
            "bull_researcher": {"claims": [], "inferences": [], "conclusion_ja": "強気"},
            "bear_researcher": {"claims": [], "inferences": [], "conclusion_ja": "弱気"},
        },
        "debate": {"rounds": [], "resolution_ja": ""},
        "portfolio_manager": {
            "proposed_rating": "BUY",
            "investment_thesis_ja": "テスト強気判断",
            "scenarios": [
                {"label": "強気", "eps": 12000, "per": 12, "probability": 0.4},
                {"label": "中立", "eps": 9000, "per": 10, "probability": 0.4},
                {"label": "弱気", "eps": 5000, "per": 8, "probability": 0.2},
            ],
        },
    })
    mock_response = MagicMock()
    mock_response.content = [mock_content]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response

    with patch.dict(sys.modules, {"anthropic": MagicMock()}):
        mock_anthropic = sys.modules["anthropic"]
        mock_anthropic.Anthropic.return_value = mock_client
        p = AnthropicProvider()
        result = p.analyze(
            prompt="test", schema={"type": "object"},
            context={}, evidence_pack={}, market_metrics={},
            company_name="キオクシアHD", ticker="285A", run_dir=Path("/tmp"),
        )

    assert result["status"] == "completed"
    assert result["result"]["portfolio_manager"]["proposed_rating"] == "BUY"
    assert result["result"]["portfolio_manager"]["investment_thesis_ja"] == "テスト強気判断"
    assert len(result["result"]["portfolio_manager"]["scenarios"]) == 3


@patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
def test_anthropic_analyze_retries_on_validation_failure():
    from llm_provider import AnthropicProvider

    bad_content = MagicMock()
    bad_content.text = json.dumps({
        "portfolio_manager": {
            "scenarios": [{"label": "x", "eps": 1, "per": 1, "probability": 1.0}],
        },
    })
    bad_response = MagicMock()
    bad_response.content = [bad_content]

    good_content = MagicMock()
    good_content.text = json.dumps({
        "analyst_reports": {
            "bull_researcher": {"claims": []}, "bear_researcher": {"claims": []},
        },
        "debate": {},
        "portfolio_manager": {
            "proposed_rating": "HOLD",
            "investment_thesis_ja": "テスト中立判断",
            "scenarios": [
                {"label": "強気", "eps": 100, "per": 10, "probability": 0.3},
                {"label": "中立", "eps": 80, "per": 8, "probability": 0.5},
                {"label": "弱気", "eps": 50, "per": 6, "probability": 0.2},
            ],
        },
    })
    good_response = MagicMock()
    good_response.content = [good_content]

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [bad_response, good_response]

    with patch.dict(sys.modules, {"anthropic": MagicMock()}):
        mock_anthropic = sys.modules["anthropic"]
        mock_anthropic.Anthropic.return_value = mock_client
        p = AnthropicProvider()
        result = p.analyze(
            prompt="test", schema={"type": "object"},
            context={}, evidence_pack={}, market_metrics={},
            company_name="", ticker="", run_dir=Path("/tmp"),
        )

    assert result["status"] == "completed"
    assert mock_client.messages.create.call_count == 2
