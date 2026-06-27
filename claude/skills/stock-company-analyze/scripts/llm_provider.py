from abc import ABC, abstractmethod
from pathlib import Path


class LLMProvider(ABC):
    """Abstract base for LLM analysis providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...

    @abstractmethod
    def analyze(
        self,
        *,
        prompt: str,
        schema: dict,
        context: dict,
        evidence_pack: dict,
        market_metrics: dict,
        company_name: str,
        ticker: str,
        run_dir: Path,
    ) -> dict:
        ...


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider — implemented in Task 3."""

    def __init__(self, model: str = "claude-sonnet-4-6"):
        self.model = model

    @property
    def provider_name(self) -> str:
        return "anthropic"

    def analyze(
        self,
        *,
        prompt: str,
        schema: dict,
        context: dict,
        evidence_pack: dict,
        market_metrics: dict,
        company_name: str,
        ticker: str,
        run_dir: Path,
    ) -> dict:
        raise NotImplementedError(
            "AnthropicProvider.analyze is implemented in Task 3"
        )


class FileProvider(LLMProvider):
    """File-based provider that reads analysis from a file — implemented in Task 5."""

    def __init__(self, result_path: Path | None = None):
        if not result_path:
            raise ValueError("result_path is required")
        self.result_path = result_path

    @property
    def provider_name(self) -> str:
        return "file"

    def analyze(
        self,
        *,
        prompt: str,
        schema: dict,
        context: dict,
        evidence_pack: dict,
        market_metrics: dict,
        company_name: str,
        ticker: str,
        run_dir: Path,
    ) -> dict:
        raise NotImplementedError(
            "FileProvider.analyze is implemented in Task 5"
        )


class CodexProvider(LLMProvider):
    """Placeholder for Codex provider."""

    @property
    def provider_name(self) -> str:
        return "codex"

    def analyze(
        self,
        *,
        prompt: str,
        schema: dict,
        context: dict,
        evidence_pack: dict,
        market_metrics: dict,
        company_name: str,
        ticker: str,
        run_dir: Path,
    ) -> dict:
        raise NotImplementedError("CodexProvider is not yet implemented")


_PROVIDER_REGISTRY: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "file": FileProvider,
    "codex": CodexProvider,
}


def get_provider(name: str, **kwargs) -> LLMProvider:
    """Look up a provider class in the registry and instantiate it."""
    cls = _PROVIDER_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown provider: {name}")
    return cls(**kwargs)
