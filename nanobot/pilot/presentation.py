from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
import re

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

    def sanitize(self, content: str, metadata: dict[str, Any]) -> PresentationResult:
        original_content = content
        blocked = []
        
        # 1. Remove <think> blocks
        content = re.sub(r'<think>.*?(?:</think>|$)', '', content, flags=re.DOTALL)
        
        # 2. Redact secrets, paths, exceptions
        patterns = [
            r'sk-[a-zA-Z0-9_-]+',
            r'(?:Bearer|API-key:|cookie:?)\s*\S+',
            r'[A-Z]:\\[^\s]+',
            r'/var/run/secrets/[^\s]+',
            r'Exception:\s*.*',
        ]
        for p in patterns:
            content = re.sub(p, '[REDACTED]', content)
            
        # 3. Recursively sanitize metadata
        def _sanitize_dict(d: dict[str, Any], path: str = "") -> dict[str, Any]:
            res = {}
            for k, v in d.items():
                full_path = f"{path}.{k}" if path else k
                if k in ("reasoning_content", "thinking_blocks", "tool_arguments", "error"):
                    blocked.append(full_path)
                    continue
                if isinstance(v, dict):
                    res[k] = _sanitize_dict(v, full_path)
                elif isinstance(v, list):
                    res[k] = [_sanitize_dict(x, full_path) if isinstance(x, dict) else x for x in v]
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
            leak_prevented=leak_prevented
        )

    def permits_event(self, event_type: Any, show_reasoning: bool) -> bool:
        from nanobot.bus.outbound_events import ProgressEvent
        if not show_reasoning and isinstance(event_type, ProgressEvent):
            if event_type.reasoning or event_type.reasoning_delta or event_type.reasoning_end:
                return False
        return True
