"""Student SLM Provider wrapping StudentInferenceService as an LLMProvider."""

from __future__ import annotations

from typing import Any, cast

from nanobot.pilot.student import StudentInferenceService
from nanobot.providers.base import LLMProvider, LLMResponse


class StudentProvider(LLMProvider):
    """LLMProvider implementation for local Student SLM model."""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        model_path: str = "~/.nanobot/models/qwen3-4b-pilot-q5_k_m.gguf",
        student_service: StudentInferenceService | None = None,
        default_model: str = "qwen3-4b-pilot-q5_k_m",
    ) -> None:
        super().__init__(api_key=api_key, api_base=api_base)
        self.student_service = student_service or StudentInferenceService(model_path=model_path)
        self._default_model = default_model

    def get_default_model(self) -> str:
        """Return default model identifier string."""
        return self._default_model

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Send a chat completion request to the student SLM model."""
        prompt_parts: list[str] = []
        for msg in messages:
            role = str(msg.get("role", "user"))
            content = msg.get("content") or ""
            if isinstance(content, list):
                blocks: list[str] = []
                for b in cast(list[Any], content):
                    if isinstance(b, dict):
                        b_dict = cast(dict[str, Any], b)
                        blocks.append(str(b_dict.get("text", "")))
                    else:
                        blocks.append(str(b))
                text_content = " ".join(blocks)
                prompt_parts.append(f"{role}: {text_content}")
            else:
                prompt_parts.append(f"{role}: {str(content)}")

        full_prompt = "\n".join(prompt_parts)

        res = self.student_service.generate(
            prompt=full_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        usage_dict = cast(dict[str, int], res.get("usage", {}))
        stop_reason_str = str(res.get("stop_reason", "stop"))
        text_str = str(res.get("text", ""))

        return LLMResponse(
            content=text_str,
            finish_reason=stop_reason_str,
            usage=usage_dict,
        )
