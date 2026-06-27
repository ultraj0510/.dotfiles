import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


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
    """Anthropic Claude provider — calls the Anthropic API directly."""

    def __init__(self, model: str = "claude-sonnet-4-6"):
        self.model = model

    @property
    def provider_name(self) -> str:
        return "anthropic"

    def analyze(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        context: dict[str, Any],
        evidence_pack: dict[str, Any],
        market_metrics: dict[str, Any],
        company_name: str,
        ticker: str,
        run_dir: Path,
    ) -> dict[str, Any]:
        import anthropic

        client = anthropic.Anthropic()

        system_prompt = (
            f"あなたは日本の機関投資家向け株式アナリストです。"
            f"{company_name} ({ticker}) の分析を行います。"
            f"出力は指定されたJSONスキーマに厳密に従ってください。"
        )

        max_retries = 2
        last_error: str | None = None
        current_prompt = prompt

        for attempt in range(max_retries + 1):
            try:
                response = client.messages.create(
                    model=self.model,
                    max_tokens=8192,
                    system=system_prompt,
                    messages=[{"role": "user", "content": current_prompt}],
                )
                raw_text: str = (
                    response.content[0].text
                    if hasattr(response.content[0], "text")
                    else str(response.content[0])
                )

                parsed = _extract_json(raw_text)

                # Validate against schema if jsonschema is available
                try:
                    import jsonschema as _js
                    _js.validate(instance=parsed, schema=schema)
                except ImportError:
                    pass

                # Validate scenarios
                pm = parsed.get("portfolio_manager", {})
                scenarios: list[dict[str, Any]] = pm.get("scenarios", [])
                if len(scenarios) != 3:
                    raise ValueError(
                        f"Expected 3 scenarios, got {len(scenarios)}"
                    )
                probs = [s["probability"] for s in scenarios]
                prob_sum = sum(probs)
                if abs(prob_sum - 1.0) > 0.01:
                    raise ValueError(
                        f"Scenario probabilities sum to {prob_sum}, expected 1.0"
                    )

                return {
                    "status": "completed",
                    "result": parsed,
                    "elapsed_seconds": 0.0,
                    "provider": "anthropic",
                    "model": self.model,
                }

            except Exception as e:
                last_error = str(e)
                if attempt < max_retries:
                    current_prompt = (
                        f"前回の出力が以下のエラーで拒否されました: {last_error}\n\n"
                        f"JSONスキーマに厳密に従い、3つのシナリオ（強気/中立/弱気）を"
                        f"確率合計1.0で出力してください。\n\n{prompt}"
                    )

        return {"status": "failed", "error": last_error or "unknown error"}


def _extract_json(text: str) -> dict[str, Any]:
    """Extract JSON object from text that may contain markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)


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
