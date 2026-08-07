"""Student SLM Provider wrapping StudentInferenceService as an LLMProvider."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, cast

from nanobot.pilot.student import StudentInferenceService, StudentUnavailableError
from nanobot.providers.base import LLMProvider, LLMResponse


class StudentProvider(LLMProvider):
    """LLMProvider implementation for local Student SLM model."""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        active_model_id: str = "qwen3-4b-pilot-q5_k_m",
        student_service: StudentInferenceService | None = None,
        default_model: str = "qwen3-4b-pilot-q5_k_m",
    ) -> None:
        super().__init__(api_key=api_key, api_base=api_base)
        self.student_service = student_service or StudentInferenceService(
            active_model_id=active_model_id
        )
        self._default_model = default_model

    def get_default_model(self) -> str:
        """Return default model identifier string."""
        return self._default_model

    def _build_prompt(self, messages: list[dict[str, Any]]) -> str:
        """Format chat messages into prompt string."""
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

        return "\n".join(prompt_parts)

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
        full_prompt = self._build_prompt(messages)

        try:
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
        except StudentUnavailableError as err:
            return LLMResponse(
                content=f"Error: {err}",
                finish_reason="error",
                usage={"prompt_tokens": 0, "completion_tokens": 0},
            )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_thinking_delta: Callable[[str], Awaitable[None]] | None = None,
        on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        """Stream response content deltas incrementally."""
        full_prompt = self._build_prompt(messages)
        accumulated_text: list[str] = []
        final_usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}
        finish_reason = "stop"

        try:
            for chunk in self.student_service.generate_stream(
                prompt=full_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            ):
                delta = chunk.get("content_delta", "")
                if delta:
                    accumulated_text.append(delta)
                    if on_content_delta:
                        await on_content_delta(delta)

                if chunk.get("stop_reason"):
                    finish_reason = str(chunk["stop_reason"])
                if chunk.get("usage"):
                    final_usage = cast(dict[str, int], chunk["usage"])

            return LLMResponse(
                content="".join(accumulated_text),
                finish_reason=finish_reason,
                usage=final_usage,
            )
        except StudentUnavailableError as err:
            return LLMResponse(
                content=f"Error: {err}",
                finish_reason="error",
                usage={"prompt_tokens": 0, "completion_tokens": 0},
            )
