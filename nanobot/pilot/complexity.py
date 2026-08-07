"""Task complexity classifier for Teacher-Student routing."""

from __future__ import annotations

import re
from typing import Literal

_CODE_PATTERN = re.compile(r"```|\b(def|class|import|function|const|let|var)\b", re.IGNORECASE)
_MATH_PATTERN = re.compile(r"[\d\s\+\-\*/=\(\)\^\.\,]{5,}|calculate|compute|equation|solve|math|proof", re.IGNORECASE)
_MULTISTEP_PATTERN = re.compile(r"step\s+\d+|first.*second|then.*finally|multi-step", re.IGNORECASE)
_HEAVY_TOOLS = {"bash", "python_interpreter", "exec", "subagent"}


class TaskComplexityClassifier:
    """Classifies task complexity as simple or complex."""

    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold

    def classify(
        self,
        message: str,
        tools_available: list[str] | None = None,
        has_media: bool = False,
    ) -> tuple[Literal["simple", "complex"], float]:
        text = message.strip()

        if has_media:
            score = 0.9
        elif _CODE_PATTERN.search(text):
            score = 0.8
        elif (tools_available and len(tools_available) > 3) or any(t in _HEAVY_TOOLS for t in (tools_available or [])):
            score = 0.85
        elif _MULTISTEP_PATTERN.search(text):
            score = 0.75
        elif _MATH_PATTERN.search(text) and len(text) > 10:
            score = 0.7
        elif len(text) < 100 and not _CODE_PATTERN.search(text) and not _MATH_PATTERN.search(text):
            score = 0.1
        else:
            score = 0.3

        decision: Literal["simple", "complex"] = "complex" if score >= self.threshold else "simple"
        return decision, score
