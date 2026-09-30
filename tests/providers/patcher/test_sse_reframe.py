"""Tests for the Anthropic SSE re-framer (regression guard for the tool-call bug)."""

from __future__ import annotations

from typing import Any

from nanobot.providers.patcher.sse import create_anthropic_sse_reframer


def _collect(events: list[dict[str, Any]], *, reverse_tool_input: bool = True) -> list[str]:
    chunks: list[str] = []

    def reverse_event(event: dict[str, Any]) -> dict[str, Any]:
        if event.get("type") == "content_block_start":
            block = event.get("content_block")
            if isinstance(block, dict) and block.get("name") == "Sessions_list":
                return {**event, "content_block": {**block, "name": "sessions_list"}}
        return event

    def reverse_input(value: str) -> str:
        return value.replace("Memory_search", "memory_search") if reverse_tool_input else value

    reframer = create_anthropic_sse_reframer(
        chunks.append,
        reverse_event=reverse_event,
        reverse_tool_input=reverse_input,
    )
    for event in events:
        reframer.on_data(f"event: {event['type']}\ndata: {_json(event)}\n\n")
    reframer.on_end()
    return chunks


def _json(data: dict[str, Any]) -> str:
    import json

    return json.dumps(data)


def _frames(chunks: list[str]) -> list[str]:
    """Split a flat output stream into frames and return their event names."""

    return [frame for frame in "".join(chunks).split("\n\n") if frame]


def test_every_emitted_frame_has_event_line() -> None:
    chunks = _collect(
        [
            {"type": "message_start", "message": {"content": []}},
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "tool_use", "name": "Sessions_list"},
            },
            {"type": "content_block_stop", "index": 1},
            {"type": "message_stop"},
        ]
    )
    frames = _frames(chunks)
    assert frames
    for frame in frames:
        assert frame.startswith("event: "), frame


def test_tool_input_delta_is_reemitted_whole_and_reversed() -> None:
    chunks = _collect(
        [
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "tool_use", "name": "Sessions_list"},
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "input_json_delta", "partial_json": '{"q":"Memory'},
            },
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "input_json_delta", "partial_json": '_search"}'},
            },
            {"type": "content_block_stop", "index": 1},
        ]
    )
    joined = "".join(chunks)
    # The fragmented deltas were suppressed and emitted once, patched.
    assert '"partial_json": "{\\"q\\":\\"memory_search\\"}"' in joined
    # Tool name was reversed on content_block_start.
    assert '"name": "sessions_list"' in joined


def test_frame_split_mid_line_is_reassembled() -> None:
    chunks: list[str] = []
    reframer = create_anthropic_sse_reframer(
        chunks.append,
        reverse_event=lambda event: event,
        reverse_tool_input=lambda value: value,
    )
    raw = (
        "event: message_start\n"
        'data: {"type":"message_start","message":{"content":[]}}\n\n'
    )
    for char in raw:
        reframer.on_data(char)
    reframer.on_end()
    assert "event: message_start" in "".join(chunks)
    import json

    payload = "".join(chunks).split("data: ", 1)[1]
    assert json.loads(payload) == {
        "type": "message_start",
        "message": {"content": []},
    }


def test_orphan_event_without_data_is_dropped() -> None:
    chunks: list[str] = []
    reframer = create_anthropic_sse_reframer(
        chunks.append,
        reverse_event=lambda event: event,
        reverse_tool_input=lambda value: value,
    )
    reframer.on_data("event: content_block_delta\n\n")
    reframer.on_end()
    assert chunks == []


def test_text_delta_is_reverse_patched() -> None:
    chunks: list[str] = []

    def reverse_event(event: dict[str, Any]) -> dict[str, Any]:
        delta = event.get("delta")
        if isinstance(delta, dict) and delta.get("type") == "text_delta":
            text = delta.get("text", "")
            if isinstance(text, str):
                return {**event, "delta": {**delta, "text": text.replace("Claude Code", "OpenClaw")}}
        return event

    reframer = create_anthropic_sse_reframer(
        chunks.append,
        reverse_event=reverse_event,
        reverse_tool_input=lambda value: value,
    )
    reframer.on_data(
        'event: content_block_delta\ndata: {"type":"content_block_delta","delta":'
        '{"type":"text_delta","text":"hi Claude Code"}}\n\n'
    )
    reframer.on_end()
    assert "OpenClaw" in "".join(chunks)
