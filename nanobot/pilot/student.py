"""Student SLM inference service using llama-cpp-python."""

from __future__ import annotations

import threading
from typing import Any, Iterator

from nanobot.pilot.distillation.registry import StudentModelResolver


class StudentUnavailableError(Exception):
    """Raised when the Student SLM model or inference engine is unavailable."""


class StudentInferenceService:
    """Thread-safe SLM inference service binding llama-cpp-python."""

    def __init__(
        self,
        active_model_id: str = "qwen3-4b-pilot-q5_k_m",
        context_length: int = 4096,
        resolver: StudentModelResolver | None = None,
    ) -> None:
        self.active_model_id = active_model_id
        self.context_length = context_length
        self._resolver = resolver or StudentModelResolver()
        self._lock = threading.Lock()
        self._llama: Any = None
        self._load_error: str | None = None

        # Resolve path and try importing llama_cpp
        try:
            model_path = self._resolver.resolve(self.active_model_id)
            if model_path.exists():
                from llama_cpp import Llama  # type: ignore[import-untyped,reportUnknownVariableType,reportMissingImports]

                self._llama = Llama(
                    model_path=str(model_path),
                    n_ctx=self.context_length,
                    verbose=False,
                )
            else:
                self._load_error = f"Model file for {active_model_id!r} does not exist"
        except Exception as err:
            self._llama = None
            self._load_error = str(err)

    @property
    def is_available(self) -> bool:
        """Return True if model is loaded and ready for inference."""
        return self._llama is not None

    def health_snapshot(self) -> dict[str, Any]:
        """Return content-free health snapshot."""
        return {
            "status": "ok" if self.is_available else "degraded",
            "active_model_id": self.active_model_id,
            "context_length": self.context_length,
            "is_available": self.is_available,
            "queue_depth": 0,
            "load_error": self._load_error if not self.is_available else None,
        }

    def generate(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """Generate response text and token metrics."""
        if not self.is_available:
            raise StudentUnavailableError(
                f"Student model {self.active_model_id!r} unavailable: {self._load_error}"
            )

        with self._lock:
            output = self._llama(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            text = output["choices"][0]["text"]
            usage = output.get("usage", {"prompt_tokens": 0, "completion_tokens": 0})
            return {
                "text": text,
                "usage": usage,
                "stop_reason": output["choices"][0].get("finish_reason", "stop"),
            }

    def generate_stream(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> Iterator[dict[str, Any]]:
        """Stream response chunks incrementally."""
        if not self.is_available:
            raise StudentUnavailableError(
                f"Student model {self.active_model_id!r} unavailable: {self._load_error}"
            )

        with self._lock:
            stream_output = self._llama(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            )
            total_prompt_tokens = 0
            total_completion_tokens = 0

            for chunk in stream_output:
                choice = chunk["choices"][0]
                delta_text = choice.get("text", "")
                if delta_text:
                    total_completion_tokens += 1
                    yield {"content_delta": delta_text, "stop_reason": None, "usage": None}

            yield {
                "content_delta": "",
                "stop_reason": "stop",
                "usage": {
                    "prompt_tokens": total_prompt_tokens,
                    "completion_tokens": total_completion_tokens,
                },
            }
