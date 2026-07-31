from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nanobot.bus.outbound_events import ProgressEvent


@dataclass(frozen=True, slots=True)
class PresentationResult:
    content: str
    metadata: dict[str, Any]
    blocked_fields: tuple[str, ...]
    leak_prevented: bool


class PresentationPolicy:
    """Pure outbound content/metadata sanitizer and event allow-policy."""

    def __init__(self, on_leak_prevented: Callable[[], None] | None = None):
        self._on_leak_prevented = on_leak_prevented

    def permits_event(self, event: Any, show_reasoning: bool) -> bool:
        if not show_reasoning and isinstance(event, ProgressEvent):
            if event.reasoning or event.reasoning_delta or event.reasoning_end:
                return False
        return True

    def sanitize(self, content: str, metadata: dict[str, Any]) -> PresentationResult:
        original_content = content
        blocked: list[str] = []

        # 1. Remove <think> blocks (closed or unclosed)
        content = re.sub(r"<think>.*?(?:</think>|$)", "", content, flags=re.DOTALL)

        # 2. Redact secrets, paths, exceptions, private keys
        patterns = [
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
            r"sk-[a-zA-Z0-9_-]+",
            r"(?i)(?:Bearer|API-key:|cookie:?|token=)\s*\S+",
            r"https?://[^:\s]+:[^@\s]+@",
            r"[a-zA-Z]:\\[^\s]+",
            r"/(?:var|etc|usr|home|root|tmp|proc|sys)/[^\s]+",
            r"Exception:\s*.*",
        ]
        for p in patterns:
            content = re.sub(p, "[REDACTED]", content)

        # 3. Recursively sanitize metadata
        def _sanitize_dict(d: dict[str, Any], path: str = "") -> dict[str, Any]:
            res: dict[str, Any] = {}
            for k, v in d.items():
                full_path = f"{path}.{k}" if path else k
                if k in ("reasoning_content", "thinking_blocks", "tool_arguments", "error"):
                    blocked.append(full_path)
                    continue
                if isinstance(v, dict):
                    res[k] = _sanitize_dict(v, full_path)
                elif isinstance(v, list):
                    res[k] = [
                        _sanitize_dict(x, full_path) if isinstance(x, dict) else x for x in v
                    ]
                else:
                    res[k] = v
            return res

        sanitized_metadata = _sanitize_dict(metadata)

        leak_prevented = (content != original_content) or bool(blocked)
        if leak_prevented and self._on_leak_prevented:
            self._on_leak_prevented()

        return PresentationResult(
            content=content,
            metadata=sanitized_metadata,
            blocked_fields=tuple(blocked),
            leak_prevented=leak_prevented,
        )
