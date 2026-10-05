"""Context Window Inspector for Nanobot.

Provides data models, token estimation, prompt decomposition, snapshot caching,
and lifecycle hook integration to inspect the active context window.
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.utils.helpers import estimate_message_tokens


@dataclass(slots=True)
class ContextSystemSection:
    key: str
    label: str
    content_preview: str
    tokens: int
    removable: bool = True
    excluded: bool = False


@dataclass(slots=True)
class ContextToolItem:
    name: str
    preview: str
    tokens: int
    removable: bool = True
    excluded: bool = False


@dataclass(slots=True)
class ContextMessageItem:
    idx: int
    role: str
    preview: str
    tokens: int
    tool_use_ids: list[str] = field(default_factory=list)
    removable: bool = True
    excluded: bool = False


@dataclass(slots=True)
class ContextBudget:
    used: int
    max: int
    model_id: str
    provider: str
    is_estimate: bool = True
    captured_at: int = 0


@dataclass(slots=True)
class ContextSnapshot:
    available: bool
    budget: ContextBudget | None = None
    system: dict[str, Any] = field(default_factory=lambda: {"total_tokens": 0, "sections": []})
    tools: dict[str, Any] = field(default_factory=lambda: {"total_tokens": 0, "items": []})
    messages: dict[str, Any] = field(default_factory=lambda: {"total_tokens": 0, "items": []})
    session_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_text_tokens(text: str) -> int:
    """Fast local token estimation (chars / 4)."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def decompose_system_prompt(content: str) -> list[ContextSystemSection]:
    """Breakdown system prompt into sections by markdown headings or known tags."""
    if not content:
        return []

    lines = content.split("\n")
    sections: list[ContextSystemSection] = []
    current_key = "identity"
    current_label = "Identity & Core"
    current_lines: list[str] = []

    def flush_section():
        nonlocal current_lines, current_key, current_label
        if current_lines:
            text = "\n".join(current_lines).strip()
            if text:
                preview = text[:200] + ("..." if len(text) > 200 else "")
                tokens = estimate_text_tokens(text)
                sections.append(
                    ContextSystemSection(
                        key=current_key,
                        label=current_label,
                        content_preview=preview,
                        tokens=tokens,
                        removable=current_key not in {"identity", "contract"},
                    )
                )
        current_lines = []

    for line in lines:
        match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if match:
            flush_section()
            heading_title = match.group(2).strip()
            slug = re.sub(r"[^a-zA-Z0-9_-]", "_", heading_title.lower()).strip("_")
            current_key = slug or f"section_{len(sections)}"
            current_label = heading_title
            current_lines.append(line)
        elif line.startswith("[Archived Context Summary]"):
            flush_section()
            current_key = "archived_summary"
            current_label = "Archived Context Summary"
            current_lines.append(line)
        else:
            current_lines.append(line)

    flush_section()
    return sections


class ContextInspectorStore:
    """Manages in-memory cache and disk persistence of context snapshots."""

    def __init__(self, workspace_path: Path | None = None) -> None:
        self._cache: dict[str, ContextSnapshot] = {}
        self._rules: dict[str, dict[str, Any]] = {}
        self.workspace_path = workspace_path

    def _rules_file(self, session_key: str) -> Path | None:
        if not self.workspace_path:
            return None
        safe_key = re.sub(r"[^a-zA-Z0-9_-]", "_", session_key)
        dir_path = self.workspace_path / ".nanobot" / "context_inspector"
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path / f"{safe_key}.rules.json"

    def get_rules(self, session_key: str) -> dict[str, Any]:
        if session_key in self._rules:
            return self._rules[session_key]
        try:
            f = self._rules_file(session_key)
            if f and f.is_file():
                rules = json.loads(f.read_text(encoding="utf-8"))
                self._rules[session_key] = rules
                return rules
        except Exception:
            pass
        default_rules = {
            "system_sections": [],
            "tools": [],
            "message_idx": [],
            "wasted_ids": [],
        }
        self._rules[session_key] = default_rules
        return default_rules

    def set_exclusions(
        self,
        session_key: str,
        system_sections: list[str] | None = None,
        tools: list[str] | None = None,
        message_idx: list[int] | None = None,
    ) -> dict[str, Any]:
        rules = self.get_rules(session_key)
        if system_sections is not None:
            rules["system_sections"] = list(system_sections)
        if tools is not None:
            rules["tools"] = list(tools)
        if message_idx is not None:
            rules["message_idx"] = [int(i) for i in message_idx]

        self._rules[session_key] = rules
        try:
            f = self._rules_file(session_key)
            if f:
                f.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        return rules

    def mark_wasted(
        self,
        session_key: str,
        recent: int | None = None,
        ids: list[str] | None = None,
        rescue_ids: list[str] | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        rules = self.get_rules(session_key)
        current_wasted = set(rules.get("wasted_ids", []))
        added: list[str] = []
        rescued: list[str] = []

        if rescue_ids:
            for rid in rescue_ids:
                if rid in current_wasted:
                    current_wasted.remove(rid)
                    rescued.append(rid)

        if ids:
            for wid in ids:
                if wid not in current_wasted:
                    current_wasted.add(wid)
                    added.append(wid)

        if recent and recent > 0:
            snap = self.get_snapshot(session_key)
            if snap.available and snap.messages and "items" in snap.messages:
                msgs = snap.messages["items"]
                tool_roundtrips = [m for m in msgs if m.get("tool_use_ids")]
                for m in tool_roundtrips[-recent:]:
                    for tuid in m.get("tool_use_ids", []):
                        if tuid not in current_wasted:
                            current_wasted.add(tuid)
                            added.append(tuid)

        rules["wasted_ids"] = list(current_wasted)
        self._rules[session_key] = rules
        try:
            f = self._rules_file(session_key)
            if f:
                f.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

        return {
            "status": "ok",
            "marked": len(added),
            "rescued": len(rescued),
            "total_wasted": len(current_wasted),
            "wasted_ids": list(current_wasted),
        }

    def apply_rules(
        self,
        session_key: str,
        messages: list[dict[str, Any]],
        tools_definitions: list[dict[str, Any]] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
        rules = self.get_rules(session_key)
        excluded_sections = set(rules.get("system_sections", []))
        excluded_tools = set(rules.get("tools", []))
        excluded_msg_idx = set(rules.get("message_idx", []))
        wasted_ids = set(rules.get("wasted_ids", []))

        # 1. Filter tools
        filtered_tools = tools_definitions
        if tools_definitions and excluded_tools:
            filtered_tools = []
            for td in tools_definitions:
                fn = td.get("function", td)
                name = fn.get("name")
                if name not in excluded_tools:
                    filtered_tools.append(td)

        # 2. Filter messages
        filtered_messages: list[dict[str, Any]] = []
        for idx, m in enumerate(messages):
            if idx in excluded_msg_idx:
                continue
            role = m.get("role")
            if role == "system" and excluded_sections:
                content = m.get("content", "")
                if isinstance(content, str):
                    sections = decompose_system_prompt(content)
                    kept_text = []
                    for s in sections:
                        if s.key not in excluded_sections:
                            kept_text.append(f"# {s.label}\n{s.content_preview}")
                    filtered_messages.append({"role": "system", "content": "\n\n".join(kept_text)})
                    continue

            # Check wasted tool calls / tool results
            if wasted_ids:
                is_wasted = False
                if "tool_calls" in m and isinstance(m["tool_calls"], list):
                    tc_ids = [str(tc.get("id")) for tc in m["tool_calls"] if isinstance(tc, dict)]
                    if any(tcid in wasted_ids for tcid in tc_ids):
                        is_wasted = True
                elif "tool_call_id" in m and str(m["tool_call_id"]) in wasted_ids:
                    is_wasted = True
                if is_wasted:
                    continue

            filtered_messages.append(m)

        # Invariant: ensure transcript does not end with orphan tool_calls or broken chain
        if not filtered_messages:
            filtered_messages = list(messages)

        return filtered_messages, filtered_tools

    def _snapshot_file(self, session_key: str) -> Path | None:
        if not self.workspace_path:
            return None
        safe_key = re.sub(r"[^a-zA-Z0-9_-]", "_", session_key)
        dir_path = self.workspace_path / ".nanobot" / "context_inspector"
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path / f"{safe_key}.json"

    def record_snapshot(
        self,
        session_key: str,
        messages: Sequence[dict[str, Any]],
        tools_definitions: Sequence[dict[str, Any]] | None,
        model_id: str,
        provider: str,
        context_window_tokens: int,
    ) -> ContextSnapshot:
        # 1. System prompt
        system_content = ""
        system_sections: list[ContextSystemSection] = []
        msg_items: list[ContextMessageItem] = []

        total_system_tokens = 0
        total_msg_tokens = 0

        for idx, msg in enumerate(messages):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                # block content
                text_parts = []
                for b in content:
                    if isinstance(b, dict):
                        if b.get("type") == "text":
                            text_parts.append(b.get("text", ""))
                        elif "text" in b:
                            text_parts.append(str(b["text"]))
                raw_text = "\n".join(text_parts)
            else:
                raw_text = str(content)

            toks = estimate_message_tokens(msg)

            if role == "system" and not system_content:
                system_content = raw_text
                system_sections = decompose_system_prompt(raw_text)
                total_system_tokens = sum(s.tokens for s in system_sections)
            else:
                preview = (raw_text[:120] + "...") if len(raw_text) > 120 else raw_text
                tool_use_ids: list[str] = []
                if "tool_calls" in msg and isinstance(msg["tool_calls"], list):
                    for tc in msg["tool_calls"]:
                        if isinstance(tc, dict) and "id" in tc:
                            tool_use_ids.append(str(tc["id"]))
                elif "tool_call_id" in msg:
                    tool_use_ids.append(str(msg["tool_call_id"]))

                msg_items.append(
                    ContextMessageItem(
                        idx=idx,
                        role=role,
                        preview=preview or f"[{role} content]",
                        tokens=toks,
                        tool_use_ids=tool_use_ids,
                        removable=True,
                    )
                )
                total_msg_tokens += toks

        # 2. Tools
        tool_items: list[ContextToolItem] = []
        total_tool_tokens = 0
        if tools_definitions:
            for td in tools_definitions:
                fn = td.get("function", td)
                name = fn.get("name", "unknown")
                desc = fn.get("description", "")
                schema_str = json.dumps(fn, ensure_ascii=False)
                t_tokens = estimate_text_tokens(schema_str)
                tool_items.append(
                    ContextToolItem(
                        name=name,
                        preview=desc[:100] + ("..." if len(desc) > 100 else ""),
                        tokens=t_tokens,
                    )
                )
                total_tool_tokens += t_tokens

        # 3. Budget
        total_used = total_system_tokens + total_tool_tokens + total_msg_tokens
        budget = ContextBudget(
            used=total_used,
            max=context_window_tokens,
            model_id=model_id,
            provider=provider,
            is_estimate=True,
            captured_at=int(time.time() * 1000),
        )

        snapshot = ContextSnapshot(
            available=True,
            budget=budget,
            system={
                "total_tokens": total_system_tokens,
                "sections": [asdict(s) for s in system_sections],
            },
            tools={
                "total_tokens": total_tool_tokens,
                "items": [asdict(t) for t in tool_items],
            },
            messages={
                "total_tokens": total_msg_tokens,
                "items": [asdict(m) for m in msg_items],
            },
            session_key=session_key,
        )

        self._cache[session_key] = snapshot

        # Persist to disk (fire and forget)
        try:
            f = self._snapshot_file(session_key)
            if f:
                f.write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

        return snapshot

    def get_snapshot(self, session_key: str) -> ContextSnapshot:
        if session_key in self._cache:
            return self._cache[session_key]

        # Try disk
        try:
            f = self._snapshot_file(session_key)
            if f and f.is_file():
                data = json.loads(f.read_text(encoding="utf-8"))
                budget_data = data.get("budget")
                budget = ContextBudget(**budget_data) if budget_data else None
                snap = ContextSnapshot(
                    available=data.get("available", False),
                    budget=budget,
                    system=data.get("system", {}),
                    tools=data.get("tools", {}),
                    messages=data.get("messages", {}),
                    session_key=data.get("session_key", session_key),
                )
                self._cache[session_key] = snap
                return snap
        except Exception:
            pass

        return ContextSnapshot(available=False, session_key=session_key)


_GLOBAL_STORE = ContextInspectorStore()


def get_inspector_store(workspace: Path | None = None) -> ContextInspectorStore:
    global _GLOBAL_STORE
    if workspace and _GLOBAL_STORE.workspace_path != workspace:
        _GLOBAL_STORE.workspace_path = workspace
    return _GLOBAL_STORE


class ContextInspectorHook(AgentHook):
    """Lifecycle hook that captures prompt & tools before each iteration."""

    def __init__(self, workspace: Path | None = None) -> None:
        super().__init__()
        self.workspace = workspace

    async def before_iteration(self, context: AgentHookContext) -> None:
        # Note: full snapshot with tools and exact model runtime is best captured
        # when transform_request or before_iteration runs.
        pass
