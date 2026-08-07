"""Student SLM inference service using llama-cpp-python with fallback."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Iterator


class StudentInferenceService:
    """Thread-safe SLM inference service."""

    def __init__(
        self,
        model_path: Path | str = "~/.nanobot/models/qwen3-4b-pilot-q5_k_m.gguf",
        context_length: int = 4096,
    ) -> None:
        self.model_path = str(Path(model_path).expanduser())
        self.context_length = context_length
        self._lock = threading.Lock()
        self._llama: Any = None

        # Try importing llama_cpp
        try:
            from llama_cpp import Llama  # pyright: ignore[reportMissingImports]

            if Path(self.model_path).exists():
                self._llama = Llama(
                    model_path=self.model_path,
                    n_ctx=self.context_length,
                    verbose=False,
                )
        except Exception:
            self._llama = None

    def generate(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """Generate response text and token metrics."""
        with self._lock:
            if self._llama is not None:
                output = self._llama(
                    prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                text = output["choices"][0]["text"]
                usage = output.get("usage", {"prompt_tokens": len(prompt) // 4, "completion_tokens": len(text) // 4})
                return {
                    "text": text,
                    "usage": usage,
                    "stop_reason": "stop",
                }

            # Fallback stub for environments without GGUF model binary
            text = f"[SLM Fallback Response to: {prompt[:30]}]"
            return {
                "text": text,
                "usage": {"prompt_tokens": len(prompt) // 4, "completion_tokens": len(text) // 4},
                "stop_reason": "stop",
            }

    def generate_stream(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> Iterator[dict[str, Any]]:
        """Stream response chunks."""
        res = self.generate(prompt, max_tokens=max_tokens, temperature=temperature)
        yield {"content_delta": res["text"], "stop_reason": "stop", "usage": res["usage"]}
