"""Redaction engine for removing credentials, paths, secrets, and size-limiting text."""

from __future__ import annotations

import re
from typing import Any, Mapping

from nanobot.pilot.types import RedactionResult

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?"
            r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        ),
    ),
    ("api_key", re.compile(r"\bsk-[a-zA-Z0-9_-]{10,}\b")),
    (
        "bearer",
        re.compile(r"\bBearer\s+[a-zA-Z0-9_\-\.=]+\b", re.IGNORECASE),
    ),
    (
        "cookie",
        re.compile(r"\bcookie\s*:\s*\S+", re.IGNORECASE),
    ),
    (
        "url_credentials",
        re.compile(r"https?://[^:\s]+:[^@\s]+@"),
    ),
    (
        "windows_path",
        re.compile(r"[a-zA-Z]:\\[^\s]+"),
    ),
    (
        "posix_path",
        re.compile(r"/(?:var|etc|usr|home|root|tmp|proc|sys)/[^\s]+"),
    ),
    (
        "exception_text",
        re.compile(r"Exception:\s*.*", re.IGNORECASE),
    ),
]

_SENSITIVE_KEY_RE = re.compile(
    r"^(?:api[-_]?key|secret|password|passwd|token|auth|authorization|cookie|private[-_]?key)$",
    re.IGNORECASE,
)


class Redactor:
    """Recursive data redactor for strings, dicts, and lists."""

    def __init__(self, max_chars: int | None = None, rules: list[str] | None = None) -> None:
        self.max_chars = max_chars
        self.rules = rules

    def redact(self, text: str, max_chars: int | None = None) -> tuple[str, set[str]]:
        res = self.redact_string(text, max_chars=max_chars)
        return res.data, res.rule_codes

    def redact_string(self, text: str, max_chars: int | None = None) -> RedactionResult:
        rule_codes: set[str] = set()
        sanitized = text

        for code, pattern in _PATTERNS:
            if pattern.search(sanitized):
                rule_codes.add(code)
                sanitized = pattern.sub("[REDACTED]", sanitized)

        limit = max_chars if max_chars is not None else self.max_chars
        if limit is not None and len(sanitized) > limit:
            sanitized = sanitized[:limit] + "...[TRUNCATED]"
            rule_codes.add("size_trimmed")

        return RedactionResult(data=sanitized, rule_codes=rule_codes)

    def redact_structure(self, value: Any, max_chars: int | None = None) -> RedactionResult:
        rule_codes: set[str] = set()
        sanitized = self._redact_value(value, rule_codes, max_chars)
        return RedactionResult(data=sanitized, rule_codes=rule_codes)

    def _redact_value(self, value: Any, rule_codes: set[str], max_chars: int | None = None) -> Any:
        if isinstance(value, str):
            res = self.redact_string(value, max_chars=max_chars)
            rule_codes.update(res.rule_codes)
            return res.data

        if isinstance(value, Mapping):
            redacted_dict: dict[str, Any] = {}
            for k, v in value.items():
                k_str = str(k)
                if _SENSITIVE_KEY_RE.search(k_str):
                    rule_codes.add("tool_argument")
                    redacted_dict[k_str] = "[REDACTED]"
                else:
                    redacted_dict[k_str] = self._redact_value(v, rule_codes, max_chars)
            return redacted_dict

        if isinstance(value, (list, tuple)):
            redacted_list = [self._redact_value(item, rule_codes, max_chars) for item in value]
            return tuple(redacted_list) if isinstance(value, tuple) else redacted_list

        return value
