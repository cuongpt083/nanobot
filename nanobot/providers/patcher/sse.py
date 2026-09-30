"""Anthropic Messages SSE stream re-framer for the OAuth patcher proxy.

Reverse-patches an Anthropic ``text/event-stream`` on the fly (tool-name
reversal, text-pattern reversal, complete-JSON tool-input reversal) and re-emits
frames that are *always* well-formed: ``event: <name>\\ndata: <json>\\n\\n``.

Why event-aware rather than line-by-line
----------------------------------------
The original forwarder processed the upstream stream line by line. For a
``tool_use`` block it suppressed each ``input_json_delta`` ``data:`` line but had
already forwarded that line's ``event: content_block_delta`` header, so the
block's ``content_block_stop`` frame arrived with no ``event:`` line. Clients
that require an ``event:`` line per message (pi-ai) silently dropped it and never
saw the tool call.

This implementation accumulates ``event:``/``data:`` lines until the blank-line
delimiter, parses the whole event, patches it, and re-emits one complete frame.
Tool-input fragments are buffered per content-block index and re-emitted whole at
``content_block_stop`` so a replace rule can never split a pattern across two
network chunks.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, cast

__all__ = ["SseReframer", "create_anthropic_sse_reframer"]


class SseReframer:
    """Stateful SSE re-framer. Feed chunks with :meth:`on_data`."""

    def __init__(
        self,
        write: Callable[[str], None],
        *,
        reverse_event: Callable[[dict[str, Any]], dict[str, Any]],
        reverse_tool_input: Callable[[str], str],
        on_reverse_tool_input: Callable[[int], None] | None = None,
    ) -> None:
        self._write = write
        self._reverse_event = reverse_event
        self._reverse_tool_input = reverse_tool_input
        self._on_reverse_tool_input = on_reverse_tool_input

        self._buffer = ""
        self._cur_event: str | None = None
        self._cur_data: list[str] = []
        # Accumulated tool-input JSON per content-block index.
        self._tool_input_accum: dict[int, str] = {}

    # ── SSE framing ──

    def on_data(self, chunk: bytes | str) -> None:
        self._buffer += chunk if isinstance(chunk, str) else chunk.decode("utf-8", "replace")
        while (newline := self._buffer.find("\n")) != -1:
            line = self._buffer[:newline]
            self._buffer = self._buffer[newline + 1 :]
            self._consume_line(line)

    def on_end(self) -> None:
        if self._buffer:
            self._consume_line(self._buffer)
            self._buffer = ""
        self._flush()

    def _consume_line(self, raw_line: str) -> None:
        line = raw_line[:-1] if raw_line.endswith("\r") else raw_line
        if line == "":
            self._flush()
        elif line.startswith("event:"):
            self._cur_event = line[6:].strip()
        elif line.startswith("data:"):
            # SSE strips a single leading space after the colon; multiple data:
            # lines join with a newline.
            value = line[5:]
            if value.startswith(" "):
                value = value[1:]
            self._cur_data.append(value)
        # id:/retry:/comment (":"-prefixed) lines are ignored — Anthropic uses none.

    def _flush(self) -> None:
        # An event with no data line (e.g. an orphan `event:` header) is dropped —
        # that orphaning was the original bug. Anthropic always pairs the two.
        if self._cur_data:
            self._handle_event(self._cur_event, "\n".join(self._cur_data))
        self._cur_event = None
        self._cur_data = []

    # ── Event handling ──

    def _write_event(self, event_name: str, data_obj: Any) -> None:
        self._write(f"event: {event_name}\ndata: {json.dumps(data_obj)}\n\n")

    def _handle_event(self, event_name: str | None, data_str: str) -> None:
        if data_str.strip() == "[DONE]":
            # OpenAI-style terminator; Anthropic doesn't use it, forward defensively.
            self._write("data: [DONE]\n\n")
            return

        try:
            raw = json.loads(data_str)
        except json.JSONDecodeError:
            # Unparseable payload — forward verbatim, preserving any event name.
            prefix = f"event: {event_name}\n" if event_name else ""
            self._write(f"{prefix}data: {data_str}\n\n")
            return
        if not isinstance(raw, dict):
            prefix = f"event: {event_name}\n" if event_name else ""
            self._write(f"{prefix}data: {data_str}\n\n")
            return
        event = cast(dict[str, object], raw)

        type_value = event.get("type")
        event_type = type_value if isinstance(type_value, str) else (event_name or "")
        index_value = event.get("index")
        index = index_value if isinstance(index_value, int) else None

        # Suppress input_json_delta fragments; accumulate the raw JSON.
        if event_type == "content_block_delta" and index is not None:
            delta_value = event.get("delta")
            if isinstance(delta_value, dict):
                delta = cast(dict[str, object], delta_value)
                partial = delta.get("partial_json")
                if delta.get("type") == "input_json_delta" and isinstance(partial, str):
                    self._tool_input_accum[index] = (
                        self._tool_input_accum.get(index, "") + partial
                    )
                    return  # re-emitted whole at content_block_stop

        # On stop: emit the patched, accumulated tool input as ONE complete delta
        # BEFORE the stop frame (consumer sees full args, then the block close).
        if event_type == "content_block_stop" and index is not None:
            accumulated = self._tool_input_accum.pop(index, None)
            if accumulated is not None:
                reversed_json = self._reverse_tool_input(accumulated)
                if reversed_json != accumulated and self._on_reverse_tool_input is not None:
                    self._on_reverse_tool_input(index)
                self._write_event(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {"type": "input_json_delta", "partial_json": reversed_json},
                    },
                )

        patched = self._reverse_event(cast(dict[str, Any], event))
        self._write_event(event_name or event_type, patched)


def create_anthropic_sse_reframer(
    write: Callable[[str], None],
    *,
    reverse_event: Callable[[dict[str, Any]], dict[str, Any]],
    reverse_tool_input: Callable[[str], str],
    on_reverse_tool_input: Callable[[int], None] | None = None,
) -> SseReframer:
    """Build an :class:`SseReframer` that writes well-formed frames via ``write``."""

    return SseReframer(
        write,
        reverse_event=reverse_event,
        reverse_tool_input=reverse_tool_input,
        on_reverse_tool_input=on_reverse_tool_input,
    )
