"""Pi RPC protocol models and types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class Command:
    id: str
    type: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = {"id": self.id, "type": self.type}
        d.update(self.params)
        return d


@dataclass
class Response:
    id: str
    type: Literal["response"]
    command: str
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Response:
        return cls(
            id=str(data.get("id") or ""),
            type="response",
            command=str(data.get("command") or ""),
            success=bool(data.get("success", False)),
            data=dict(data.get("data") or {}) if isinstance(data.get("data"), dict) else {},
            error=str(data.get("error")) if data.get("error") is not None else None,
        )


@dataclass
class Event:
    type: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawEvent(Event):
    """Fallback event for unhandled or future Pi event types."""
    pass


@dataclass
class AgentStartEvent(Event):
    type: Literal["agent_start"] = "agent_start"


@dataclass
class AgentEndEvent(Event):
    type: Literal["agent_end"] = "agent_end"


@dataclass
class AgentSettledEvent(Event):
    type: Literal["agent_settled"] = "agent_settled"


@dataclass
class TurnStartEvent(Event):
    type: Literal["turn_start"] = "turn_start"


@dataclass
class TurnEndEvent(Event):
    type: Literal["turn_end"] = "turn_end"


@dataclass
class MessageStartEvent(Event):
    type: Literal["message_start"] = "message_start"
    role: str = ""
    content: Any = None


@dataclass
class MessageUpdateEvent(Event):
    type: Literal["message_update"] = "message_update"
    assistant_event: dict[str, Any] = field(default_factory=dict)


@dataclass
class MessageEndEvent(Event):
    type: Literal["message_end"] = "message_end"
    role: str = ""
    content: Any = None


@dataclass
class ToolExecutionStartEvent(Event):
    type: Literal["tool_execution_start"] = "tool_execution_start"
    tool_name: str = ""
    tool_call_id: str = ""
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolExecutionUpdateEvent(Event):
    type: Literal["tool_execution_update"] = "tool_execution_update"
    tool_call_id: str = ""


@dataclass
class ToolExecutionEndEvent(Event):
    type: Literal["tool_execution_end"] = "tool_execution_end"
    tool_call_id: str = ""
    result: Any = None
    is_error: bool = False


@dataclass
class ExtensionUiRequestEvent(Event):
    type: Literal["extension_ui_request"] = "extension_ui_request"
    id: str = ""
    method: str = ""
    params: dict[str, Any] = field(default_factory=dict)


def parse_rpc_event(raw: dict[str, Any]) -> Event:
    ev_type = str(raw.get("type") or "")
    if ev_type == "agent_start":
        return AgentStartEvent(type="agent_start", raw=raw)
    if ev_type == "agent_end":
        return AgentEndEvent(type="agent_end", raw=raw)
    if ev_type == "agent_settled":
        return AgentSettledEvent(type="agent_settled", raw=raw)
    if ev_type == "turn_start":
        return TurnStartEvent(type="turn_start", raw=raw)
    if ev_type == "turn_end":
        return TurnEndEvent(type="turn_end", raw=raw)
    if ev_type == "message_start":
        msg = raw.get("message") or {}
        return MessageStartEvent(
            type="message_start",
            role=str(msg.get("role") or ""),
            content=msg.get("content"),
            raw=raw,
        )
    if ev_type == "message_update":
        return MessageUpdateEvent(
            type="message_update",
            assistant_event=dict(raw.get("assistantMessageEvent") or {}),
            raw=raw,
        )
    if ev_type == "message_end":
        msg = raw.get("message") or {}
        return MessageEndEvent(
            type="message_end",
            role=str(msg.get("role") or ""),
            content=msg.get("content"),
            raw=raw,
        )
    if ev_type == "tool_execution_start":
        return ToolExecutionStartEvent(
            type="tool_execution_start",
            tool_name=str(raw.get("toolName") or ""),
            tool_call_id=str(raw.get("toolCallId") or ""),
            args=dict(raw.get("args") or {}),
            raw=raw,
        )
    if ev_type == "tool_execution_update":
        return ToolExecutionUpdateEvent(
            type="tool_execution_update",
            tool_call_id=str(raw.get("toolCallId") or ""),
            raw=raw,
        )
    if ev_type == "tool_execution_end":
        return ToolExecutionEndEvent(
            type="tool_execution_end",
            tool_call_id=str(raw.get("toolCallId") or ""),
            result=raw.get("result"),
            is_error=bool(raw.get("isError", False)),
            raw=raw,
        )
    if ev_type == "extension_ui_request":
        return ExtensionUiRequestEvent(
            type="extension_ui_request",
            id=str(raw.get("id") or ""),
            method=str(raw.get("method") or ""),
            params=dict(raw.get("params") or {}),
            raw=raw,
        )
    return RawEvent(type=ev_type, raw=raw)
