import pytest
from pathlib import Path


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
