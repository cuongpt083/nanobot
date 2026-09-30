"""Fake Pi CLI for testing PiBackend in RPC mode."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def main() -> None:
    scenario = os.environ.get("FAKE_PI_SCENARIO", "").strip()

    if scenario == "hang_on_start":
        time.sleep(300)
        sys.exit(0)

    session_file = os.path.join(os.getcwd(), "fake-pi-session.jsonl")

    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except Exception:
            continue

        cmd_type = req.get("type")
        req_id = req.get("id")

        if cmd_type == "prompt":
            # Acknowledge prompt
            sys.stdout.write(
                json.dumps({
                    "id": req_id,
                    "type": "response",
                    "command": "prompt",
                    "success": True,
                })
                + "\n"
            )
            sys.stdout.flush()

            if scenario == "hang":
                time.sleep(300)
                continue

            if scenario.startswith("write_file:"):
                _, fpath, content = scenario.split(":", 2)
                target = Path(fpath)
                if not target.is_absolute():
                    target = Path.cwd() / target
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

            if scenario == "malformed_lines":
                # Emit \r\n, broken JSON, line with U+2028
                sys.stdout.write("MALFORMED JSON LINE\r\n")
                sys.stdout.write('{"type": "unknown_event_type", "data": 123}\n')
                sys.stdout.write('{"type": "tool_execution_start", "toolName": "edit\u2028line"}\n')
                sys.stdout.flush()

            if scenario == "ui_dialog":
                # Emit an extension UI confirm request and wait for extension_ui_response
                sys.stdout.write(
                    json.dumps({
                        "type": "extension_ui_request",
                        "id": "dlg-test-1",
                        "dialogType": "confirm",
                        "title": "Do you confirm?",
                    })
                    + "\n"
                )
                sys.stdout.flush()

                # Read response from stdin
                resp_line = sys.stdin.readline()
                if resp_line:
                    resp_obj = json.loads(resp_line.strip())
                    if not resp_obj.get("cancelled"):
                        sys.stderr.write("Expected cancelled=True in UI response\n")

            # Emit normal sequence: tool execution, message, agent_settled
            sys.stdout.write(
                json.dumps({
                    "type": "tool_execution_start",
                    "toolName": "edit",
                    "toolCallId": "call-1",
                    "arguments": {"path": "test.txt"},
                })
                + "\n"
            )
            sys.stdout.write(
                json.dumps({
                    "type": "tool_execution_end",
                    "toolName": "edit",
                    "toolCallId": "call-1",
                })
                + "\n"
            )
            sys.stdout.write(
                json.dumps({
                    "type": "message_start",
                    "delta": "Completed edit\n",
                })
                + "\n"
            )
            sys.stdout.write(
                json.dumps({
                    "type": "agent_settled",
                })
                + "\n"
            )
            sys.stdout.flush()

        elif cmd_type == "steer":
            sys.stdout.write(
                json.dumps({
                    "id": req_id,
                    "type": "response",
                    "command": "steer",
                    "success": True,
                })
                + "\n"
            )
            sys.stdout.flush()

        elif cmd_type == "abort":
            sys.stdout.write(
                json.dumps({
                    "id": req_id,
                    "type": "response",
                    "command": "abort",
                    "success": True,
                })
                + "\n"
            )
            sys.stdout.flush()

        elif cmd_type == "get_session_stats":
            sys.stdout.write(
                json.dumps({
                    "id": req_id,
                    "type": "response",
                    "command": "get_session_stats",
                    "success": True,
                    "data": {
                        "sessionFile": session_file,
                        "sessionId": "fake-pi-session-001",
                        "tokens": {
                            "input": 1000,
                            "output": 150,
                            "thinking": 20,
                            "cacheRead": 0,
                            "total": 1170,
                        },
                        "cost": 0.0025,
                    },
                })
                + "\n"
            )
            sys.stdout.flush()

        elif cmd_type == "get_last_assistant_text":
            sys.stdout.write(
                json.dumps({
                    "id": req_id,
                    "type": "response",
                    "command": "get_last_assistant_text",
                    "success": True,
                    "data": {
                        "text": "Completed edit\n",
                    },
                })
                + "\n"
            )
            sys.stdout.flush()


if __name__ == "__main__":
    main()
