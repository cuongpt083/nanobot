"""Tests for ChannelManager routing of model reasoning content.

Reasoning is delivered through plugin streaming primitives
(``send_reasoning_delta`` / ``send_reasoning_end``) so each channel
controls in-place rendering — mirroring the existing answer ``send_delta``
/ ``stream_end`` pair. The manager forwards reasoning frames only to
channels that opt in via ``channel.show_reasoning``; plugins without a
low-emphasis UI primitive keep the base no-op and the content silently
drops at dispatch.

One-shot reasoning frames are represented as typed progress events and
``BaseChannel.send_reasoning`` expands them to a single delta + end pair so
plugins only implement the streaming primitives.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.progress_hook import AgentProgressHook
from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import (
    ProgressEvent,
    outbound_event_from_message,
    outbound_message_for_event,
)
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager
from nanobot.channels.websocket.runtime import WebSocketChannel
from nanobot.config.schema import Config
from nanobot.providers.base import ToolCallRequest


class _MockChannel(BaseChannel):
    name = "mock"
    display_name = "Mock"

    def __init__(self, config, bus):
        super().__init__(config, bus)
        self._send_mock = AsyncMock()
        self._delta_mock = AsyncMock()
        self._end_mock = AsyncMock()
        self._file_edit_mock = AsyncMock()

    async def start(self):  # pragma: no cover - not exercised
        pass

    async def stop(self):  # pragma: no cover - not exercised
        pass

    async def send(self, msg):
        return await self._send_mock(msg)

    async def send_reasoning_delta(self, chat_id, delta, metadata=None, *, stream_id=None):
        return await self._delta_mock(chat_id, delta, metadata, stream_id=stream_id)

    async def send_reasoning_end(self, chat_id, metadata=None, *, stream_id=None):
        return await self._end_mock(chat_id, metadata, stream_id=stream_id)

    async def send_file_edit_events(self, chat_id, edits, metadata=None):
        return await self._file_edit_mock(chat_id, edits, metadata)


@pytest.fixture
def manager() -> ChannelManager:
    config = Config.model_validate({"channels": {"websocket": {"enabled": False}}})
    mgr = ChannelManager(config, MessageBus())
    mgr.channels["mock"] = _MockChannel({}, mgr.bus)
    return mgr


def test_websocket_gateway_uses_configured_workspace_restriction(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "nanobot.webui.workspaces.read_webui_default_access_mode",
        lambda: "default",
    )
    config = Config.model_validate(
        {
            "agents": {"defaults": {"workspace": str(tmp_path)}},
            "tools": {"restrictToWorkspace": True},
            "channels": {
                "websocket": {
                    "enabled": True,
                    "websocketRequiresToken": False,
                },
            },
        }
    )

    mgr = ChannelManager(config, MessageBus(), webui_static_dist=False)
    channel = mgr.channels["websocket"]

    scope = channel.gateway.workspaces.default_scope()
    assert scope.project_path == tmp_path
    assert scope.restrict_to_workspace is True


@pytest.mark.asyncio
async def test_reasoning_delta_routes_to_send_reasoning_delta(manager):
    channel = manager.channels["mock"]
    channel.show_reasoning = True
    msg = outbound_message_for_event(
        channel="mock",
        chat_id="c1",
        event=ProgressEvent(content="step-by-step", reasoning_delta=True, stream_id="r1"),
    )
    await manager._send_once(channel, msg)
    channel._delta_mock.assert_awaited_once()
    args = channel._delta_mock.await_args.args
    assert args[0] == "c1"
    assert args[1] == "step-by-step"
    assert channel._delta_mock.await_args.kwargs["stream_id"] == "r1"
    channel._send_mock.assert_not_awaited()
    channel._end_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_reasoning_end_routes_to_send_reasoning_end(manager):
    channel = manager.channels["mock"]
    channel.show_reasoning = True
    msg = outbound_message_for_event(
        channel="mock",
        chat_id="c1",
        event=ProgressEvent(reasoning_end=True, stream_id="r1"),
    )
    await manager._send_once(channel, msg)
    channel._end_mock.assert_awaited_once()
    assert channel._end_mock.await_args.kwargs["stream_id"] == "r1"
    channel._delta_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_one_shot_reasoning_expands_to_delta_plus_end(manager):
    """One-shot reasoning expands to a single delta + end."""
    channel = manager.channels["mock"]
    channel.show_reasoning = True
    msg = outbound_message_for_event(
        channel="mock",
        chat_id="c1",
        event=ProgressEvent(content="one-shot reasoning", reasoning=True),
    )
    await manager._send_once(channel, msg)
    channel._delta_mock.assert_awaited_once()
    channel._end_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_drops_reasoning_when_channel_opts_out(manager):
    channel = manager.channels["mock"]
    channel.show_reasoning = False
    msg = outbound_message_for_event(
        channel="mock",
        chat_id="c1",
        event=ProgressEvent(content="hidden thinking", reasoning_delta=True),
    )
    await manager.bus.publish_outbound(msg)

    await _pump_one(manager)

    channel._delta_mock.assert_not_awaited()
    channel._end_mock.assert_not_awaited()
    channel._send_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_hidden_reasoning_is_dropped_before_presentation_sanitization(manager, monkeypatch):
    channel = manager.channels["mock"]
    channel.show_reasoning = False
    sanitize = AsyncMock()
    monkeypatch.setattr(manager.presentation_policy, "sanitize", sanitize)
    msg = outbound_message_for_event(
        channel="mock",
        chat_id="c1",
        event=ProgressEvent(content="<think>hidden</think>", reasoning_delta=True),
    )

    await manager._send_once(channel, msg)

    sanitize.assert_not_called()
    channel._delta_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_delivers_reasoning_when_channel_opts_in(manager):
    channel = manager.channels["mock"]
    channel.show_reasoning = True
    for chunk in ("first ", "second"):
        await manager.bus.publish_outbound(outbound_message_for_event(
            channel="mock",
            chat_id="c1",
            event=ProgressEvent(content=chunk, reasoning_delta=True, stream_id="r1"),
        ))
    await manager.bus.publish_outbound(outbound_message_for_event(
        channel="mock",
        chat_id="c1",
        event=ProgressEvent(reasoning_end=True, stream_id="r1"),
    ))

    await _pump_one(manager)

    assert channel._delta_mock.await_count == 2
    channel._end_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_silently_drops_reasoning_for_unknown_channel(manager):
    msg = outbound_message_for_event(
        channel="ghost",
        chat_id="c1",
        event=ProgressEvent(content="nobody home", reasoning_delta=True),
    )
    await manager.bus.publish_outbound(msg)

    await _pump_one(manager)

    manager.channels["mock"]._delta_mock.assert_not_awaited()
    manager.channels["mock"]._send_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_base_channel_reasoning_primitives_are_noop_safe():
    """Plugins that don't override the streaming primitives must not blow up."""

    class _Plain(BaseChannel):
        name = "plain"
        display_name = "Plain"

        async def start(self):  # pragma: no cover
            pass

        async def stop(self):  # pragma: no cover
            pass

        async def send(self, msg):  # pragma: no cover
            pass

    channel = _Plain({}, MessageBus())
    assert await channel.send_reasoning_delta("c", "x") is None
    assert await channel.send_reasoning_end("c") is None
    # And the one-shot wrapper translates without raising.
    assert await channel.send_reasoning(
        OutboundMessage(channel="plain", chat_id="c", content="x", metadata={})
    ) is None


@pytest.mark.asyncio
async def test_file_edit_events_route_to_channel_capability(manager):
    channel = manager.channels["mock"]
    edits = [{"version": 1, "phase": "start", "path": "src/app.py"}]
    msg = outbound_message_for_event(
        channel="mock",
        chat_id="c1",
        event=ProgressEvent(file_edit_events=edits),
    )

    await manager._send_once(channel, msg)

    channel._file_edit_mock.assert_awaited_once_with(
        "c1", [{"version": 1, "phase": "start", "path": "[REDACTED]"}], msg.metadata
    )
    channel._send_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_typed_file_edit_event_routes_to_channel_capability(manager):
    channel = manager.channels["mock"]
    edits = [{"version": 1, "phase": "start", "path": "src/app.py"}]
    msg = outbound_message_for_event(
        channel="mock",
        chat_id="c1",
        event=ProgressEvent(file_edit_events=edits),
    )

    await manager._send_once(channel, msg)

    channel._file_edit_mock.assert_awaited_once_with(
        "c1", [{"version": 1, "phase": "start", "path": "[REDACTED]"}], msg.metadata
    )
    channel._send_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_tool_event_payload_is_sanitized_before_channel_delivery(manager):
    channel = manager.channels["mock"]
    raw_events = [{
        "version": 1,
        "phase": "error",
        "call_id": "call-1",
        "name": "exec",
        "arguments": {"token": "super-secret"},
        "result": "C:\\Users\\Admin\\secret.txt",
        "error": "Bearer super-secret",
        "files": [{"path": "/var/private.txt"}],
        "embeds": [{"url": "https://user:password@example.test"}],
    }]
    msg = outbound_message_for_event(
        channel="mock",
        chat_id="c1",
        event=ProgressEvent(tool_events=raw_events),
    )

    await manager._send_once(channel, msg)

    delivered = channel._send_mock.await_args.args[0]
    delivered_event = outbound_event_from_message(delivered)
    assert isinstance(delivered_event, ProgressEvent)
    assert delivered_event.tool_events == [{
        "version": 1,
        "phase": "error",
        "call_id": "call-1",
        "name": "exec",
    }]
    assert "super-secret" not in str(delivered_event.tool_events)
    assert raw_events[0]["arguments"] == {"token": "super-secret"}


@pytest.mark.asyncio
async def test_websocket_file_edit_delivery_and_transcript_redact_paths():
    channel = WebSocketChannel.__new__(WebSocketChannel)
    connection = object()
    channel._subs = {"c1": {connection}}
    channel._persist_turn_transcript_event = MagicMock(return_value=True)
    channel._safe_send_to = AsyncMock()
    raw_edits = [{"version": 1, "phase": "end", "path": "C:\\Users\\Admin\\secret.txt"}]

    await channel.send_file_edit_events("c1", raw_edits)

    persisted = channel._persist_turn_transcript_event.call_args.args[1]
    wire_payload = json.loads(channel._safe_send_to.await_args.args[1])
    assert persisted["edits"] == [{"version": 1, "phase": "end", "path": "[REDACTED]"}]
    assert wire_payload["edits"] == persisted["edits"]
    assert "C:\\Users" not in str(persisted)
    assert raw_edits[0]["path"] == "C:\\Users\\Admin\\secret.txt"


@pytest.mark.asyncio
async def test_tool_hint_does_not_leak_arguments_to_websocket_or_transcript():
    progress: list[str] = []

    async def on_progress(content, **_kwargs):
        progress.append(content)

    hook = AgentProgressHook(on_progress=on_progress)
    context = MagicMock()
    context.tool_calls = [
        ToolCallRequest(
            id="call-1",
            name="exec",
            arguments={"command": "echo ordinary-secret private/plan.md"},
        )
    ]
    context.response = None
    context.streamed_content = True
    await hook.before_execute_tools(context)

    channel = WebSocketChannel.__new__(WebSocketChannel)
    connection = object()
    channel._subs = {"c1": {connection}}
    channel._persist_turn_transcript_event = MagicMock(return_value=True)
    channel._safe_send_to = AsyncMock()
    channel._media = MagicMock()
    channel._media.rewrite_local_markdown_images.side_effect = lambda text: text
    hint = progress[0]
    await channel.send(
        OutboundMessage(
            channel="websocket",
            chat_id="c1",
            content=hint,
            event=ProgressEvent(content=hint, tool_hint=True),
        )
    )

    persisted = channel._persist_turn_transcript_event.call_args.args[1]
    wire_payload = json.loads(channel._safe_send_to.await_args.args[1])
    assert "ordinary-secret" not in hint
    assert "private/plan.md" not in hint
    assert "ordinary-secret" not in str(persisted)
    assert "private/plan.md" not in str(persisted)
    assert "ordinary-secret" not in wire_payload["text"]
    assert "private/plan.md" not in wire_payload["text"]


@pytest.mark.asyncio
async def test_base_channel_file_edit_events_are_noop_safe():
    class _Plain(BaseChannel):
        name = "plain"
        display_name = "Plain"

        async def start(self):  # pragma: no cover
            pass

        async def stop(self):  # pragma: no cover
            pass

        async def send(self, msg):  # pragma: no cover
            raise AssertionError("file edit events should not call send")

    channel = _Plain({}, MessageBus())
    assert await channel.send_file_edit_events("c", [{"path": "a.py"}]) is None


@pytest.mark.asyncio
async def test_reasoning_routing_does_not_consult_send_progress(manager):
    """`show_reasoning` is orthogonal to `send_progress` — turning off
    progress streaming must not silence reasoning."""
    channel = manager.channels["mock"]
    channel.send_progress = False
    channel.show_reasoning = True
    await manager.bus.publish_outbound(outbound_message_for_event(
        channel="mock",
        chat_id="c1",
        event=ProgressEvent(content="still surfaces", reasoning_delta=True),
    ))

    await _pump_one(manager)

    channel._delta_mock.assert_awaited_once()


async def _pump_one(manager: ChannelManager) -> None:
    """Process currently queued messages through the reasoning dispatch branch."""

    async def dispatch_one(msg: OutboundMessage) -> None:
        event = outbound_event_from_message(msg)
        if isinstance(event, ProgressEvent) and (
            event.reasoning_delta
            or event.reasoning_end
            or event.reasoning
        ):
            channel = manager.channels.get(msg.channel)
            if channel is not None and channel.show_reasoning:
                await manager._send_with_retry(channel, msg)

    await dispatch_one(await asyncio.wait_for(manager.bus.consume_outbound(), timeout=1.0))
    while True:
        try:
            await dispatch_one(manager.bus.outbound.get_nowait())
        except asyncio.QueueEmpty:
            break
