"""Student LLM Provider wrapping StudentInferenceService."""

from __future__ import annotations

from typing import Any

from nanobot.pilot.student import StudentInferenceService
from nanobot.providers.base import LLMProvider, LLMResponse


class StudentProvider(LLMProvider):
    """LLMProvider implementation for fine-tuned GGUF SLM model."""

    def __init__(
        self,
        service: StudentInferenceService | None = None,
        model_name: str = "qwen3-4b-instruct-q5_k_m",
        api_key: str | None = None,
        api_base: str | None = None,
    ) -> None:
        super().__init__(api_key=api_key, api_base=api_base)
        self._service = service or StudentInferenceService()
        self._model_name = model_name

    @property
    def model(self) -> str:
        return self._model_name

    def get_default_model(self) -> str:
        return self._model_name

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        prompt = "\n".join(
            m.get("content", "") for m in messages if isinstance(m.get("content"), str)
        )

        try:
            res = self._service.generate(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return LLMResponse(
                content=res["text"],
                finish_reason=res.get("stop_reason", "stop"),
                usage=res.get("usage", {}),
            )
        except Exception as ex:
            return LLMResponse(
                content=None,
                finish_reason="error",
                error_kind="student_error",
                error_code=str(ex),
            )
