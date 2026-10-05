"""Router mapping requested models to authenticated on-device providers."""

from __future__ import annotations

from nanobot.config.loader import load_config
from nanobot.llm_proxy.keys import ProxyApiKey
from nanobot.providers.base import LLMProvider
from nanobot.providers.factory import make_provider


class ProxyRouter:
    """Resolves incoming model requests to authenticated providers."""

    def __init__(self) -> None:
        pass

    def resolve(
        self,
        requested_model: str,
        key: ProxyApiKey,
    ) -> tuple[LLMProvider | None, str, str | None]:
        """Resolve a requested model to an active LLMProvider.

        Returns (provider, effective_model_id, error_message).
        """
        if not requested_model:
            return None, "", "Missing 'model' parameter in request"

        config = load_config()

        # Check allowed providers on key
        # Model matching heuristics:
        lower_model = requested_model.lower()

        # 1. Check Anthropic OAuth
        if ("claude" in lower_model or "anthropic" in lower_model) and config.providers.anthropic_oauth.enabled:
            if key.allowed_providers is None or "anthropic_oauth" in key.allowed_providers:
                try:
                    provider = make_provider(config, preset_name=None, model=requested_model)
                    return provider, requested_model, None
                except Exception:
                    pass

        # 2. Check Antigravity / Gemini OAuth
        if ("gemini" in lower_model or "antigravity" in lower_model) and config.providers.antigravity.enabled:
            if key.allowed_providers is None or "antigravity" in key.allowed_providers:
                try:
                    provider = make_provider(config, preset_name=None, model=requested_model)
                    return provider, requested_model, None
                except Exception:
                    pass

        # 3. Check OpenAI Codex OAuth
        if ("gpt" in lower_model or "codex" in lower_model) and getattr(config.providers, "openai_codex", None):
            if key.allowed_providers is None or "openai_codex" in key.allowed_providers:
                try:
                    provider = make_provider(config, preset_name=None, model=requested_model)
                    return provider, requested_model, None
                except Exception:
                    pass

        # 4. Fallback to default configured provider via factory
        try:
            provider = make_provider(config, preset_name=None, model=requested_model)
            return provider, requested_model, None
        except Exception as e:
            return None, requested_model, f"Unable to route model '{requested_model}': {e}"
