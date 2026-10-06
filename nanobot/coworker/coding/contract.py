"""Structured task contract definition for coding tasks."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

_VAGUE_CRITERION = re.compile(
    r"^(ok|done|works|looks good|it works|good enough|fine)[.!]?$",
    re.IGNORECASE,
)


@dataclass
class CodingContract:
    """Explicit, structured contract for coding delegations."""

    objective: str
    context: str
    acceptance_criteria: list[str]
    constraints: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    acceptance_cmd: str | None = None
    files: list[str] = field(default_factory=list)
    mode: Literal["plan_first", "auto"] = "plan_first"
    fix_rounds: int | None = None

    def validate(self, *, min_context_chars: int = 120) -> list[str]:
        """Validate required fields according to Phase 3.1 policy."""
        errors: list[str] = []
        if not self.objective or not self.objective.strip():
            errors.append("Contract missing required 'objective': specify a clear, bounded task objective.")

        cleaned_ctx = (self.context or "").strip()
        if len(cleaned_ctx) < min_context_chars:
            errors.append(
                f"Contract 'context' too brief ({len(cleaned_ctx)} chars < minimum {min_context_chars}). "
                "Provide detailed architecture context, decisions made, or reference files."
            )

        if not self.acceptance_criteria or len(self.acceptance_criteria) == 0:
            errors.append(
                "Contract missing 'acceptance_criteria': specify at least one verifiable acceptance criterion."
            )

        return errors

    def quality_warnings(self) -> list[str]:
        """Non-blocking hints; a weak contract still starts, but quality will suffer."""
        warnings: list[str] = []
        if self.mode == "plan_first" and not (self.acceptance_cmd or "").strip():
            warnings.append(
                "No 'acceptance' command set (e.g. pytest -q). "
                "The settle gate cannot verify the result automatically."
            )
        for index, criterion in enumerate(self.acceptance_criteria):
            text = (criterion or "").strip()
            if len(text) < 12 or _VAGUE_CRITERION.fullmatch(text):
                warnings.append(
                    f"acceptance_criteria[{index}] looks hard to verify ({text!r}). "
                    "Prefer a measurable check (test name, command, or observable file/behavior)."
                )
        return warnings

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CodingContract:
        valid_fields = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def write_task_contract_json(
        self,
        target_path: Path,
        *,
        task_id: str,
        worktree_root: Path,
        bridge_mode: Literal["plan", "implement", "review"] = "implement",
        deny_commands: list[str] | None = None,
        deny_read: list[str] | None = None,
        max_continuations: int = 2,
        acceptance_timeout_s: int = 600,
        ask_enabled: bool = True,
        plan: str | None = None,
    ) -> Path:
        """Serialize complete task-contract.json for nanobot-bridge.ts consumption."""
        contract_data = {
            "task_id": task_id,
            "mode": bridge_mode,
            "root": str(worktree_root),
            "write_roots": [str(worktree_root)],
            "deny_commands": deny_commands
            if deny_commands is not None
            else ["^git\\s+push", "^git\\s+remote", "curl[^|]*\\|\\s*(ba)?sh"],
            "deny_read": deny_read
            if deny_read is not None
            else ["~/.ssh/**", "~/.aws/**", "**/.env*"],
            "contract": {
                "objective": self.objective,
                "context": self.context,
                "constraints": self.constraints,
                "acceptance_criteria": self.acceptance_criteria,
                "acceptance_cmd": self.acceptance_cmd or "",
                "out_of_scope": self.out_of_scope,
                "files": self.files,
            },
            "plan": plan or "",
            "settle": {
                "max_continuations": max_continuations,
                "acceptance_timeout_s": acceptance_timeout_s,
            },
            "ask": {
                "enabled": ask_enabled,
            },
        }

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(contract_data, indent=2), encoding="utf-8")
        return target_path
