"""Fake Pi CLI for testing the v2 RPC client (PiClient) and orchestrator.

Speaks the Pi 1.x RPC protocol: handshake (``get_state``/``get_commands``), ``prompt``
with ``disposition``, ``get_entries`` (custom ``nanobot_*`` entries), session stats and
the model/thinking RPCs. Report entries are derived from the prompt text so worker and
reviewer processes each get the right report without extra env wiring.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any


def main() -> None:
    if "--version" in sys.argv:
        sys.stdout.write("1.0.2\n")
        sys.stdout.flush()
        return

    scenario = os.environ.get("FAKE_PI_SCENARIO", "").strip()
    review_verdict = os.environ.get("FAKE_PI_REVIEW_VERDICT", "pass").strip() or "pass"

    if scenario == "hang_on_start":
        time.sleep(300)
        sys.exit(0)

    session_file = os.path.join(os.getcwd(), "fake-pi-session.jsonl")
    entries: list[dict[str, Any]] = []
    counter = {"n": 0}

    def respond(req_id: str | None, command: str, *, data: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {
            "id": req_id,
            "type": "response",
            "command": command,
            "success": True,
        }
        if data is not None:
            payload["data"] = data
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()

    def add_entry(custom_type: str, data: dict[str, Any]) -> None:
        counter["n"] += 1
        entries.append({
            "id": f"entry-{counter['n']}",
            "parentId": None,
            "type": "custom",
            "customType": custom_type,
            "data": data,
        })

    def emit_report_for(message: str) -> None:
        if "kind='plan'" in message:
            add_entry("nanobot_report", {
                "kind": "plan",
                "summary": "Fake plan summary",
                "plan_steps": ["Step one", "Step two"],
                "open_questions": [],
            })
        elif "kind='review'" in message:
            findings = json.loads(os.environ.get("FAKE_PI_REVIEW_FINDINGS", "[]"))
            add_entry("nanobot_report", {
                "kind": "review",
                "verdict": review_verdict,
                "summary": "Fake review summary",
                "findings": findings,
            })
        elif "kind='implementation'" in message:
            add_entry("nanobot_report", {
                "kind": "implementation",
                "status": "done",
                "summary": "Fake implementation summary",
                "changes": [],
                "tests_run": [],
            })

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

        if cmd_type == "get_state":
            respond(req_id, "get_state", data={"model": "fake-model", "provider": "fake", "thinking": "high"})
        elif cmd_type == "get_commands":
            respond(req_id, "get_commands", data={"commands": [{"name": "nanobot-mode"}, {"name": "help"}]})
        elif cmd_type == "get_available_models":
            respond(req_id, "get_available_models", data={"models": [{"provider": "fake", "modelId": "fake-model"}]})
        elif cmd_type == "get_available_thinking_levels":
            respond(req_id, "get_available_thinking_levels", data={"levels": ["off", "low", "medium", "high"]})
        elif cmd_type == "set_model":
            respond(req_id, "set_model", data={"provider": req.get("provider"), "modelId": req.get("modelId")})
        elif cmd_type == "set_thinking_level":
            respond(req_id, "set_thinking_level")
        elif cmd_type == "export_html":
            respond(req_id, "export_html", data={"path": req.get("outputPath") or "session.html"})
        elif cmd_type == "get_entries":
            since = req.get("since")
            filtered = entries
            if since:
                ids = [e["id"] for e in entries]
                if since in ids:
                    filtered = entries[ids.index(since) + 1:]
            leaf_id = entries[-1]["id"] if entries else None
            respond(req_id, "get_entries", data={"entries": filtered, "leafId": leaf_id})
        elif cmd_type == "get_session_stats":
            respond(req_id, "get_session_stats", data={
                "sessionFile": session_file,
                "sessionId": "fake-pi-session-001",
                "tokens": {"input": 1000, "output": 150, "thinking": 20, "cacheRead": 0, "total": 1170},
                "cost": 0.0025,
            })
        elif cmd_type == "get_last_assistant_text":
            respond(req_id, "get_last_assistant_text", data={"text": "Completed edit\n"})
        elif cmd_type == "steer":
            respond(req_id, "steer")
        elif cmd_type == "abort":
            respond(req_id, "abort")
        elif cmd_type == "prompt":
            message = str(req.get("message", ""))
            handled = message.startswith("/")
            respond(req_id, "prompt", data={"disposition": "handled" if handled else "started"})
            if handled:
                continue

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
                sys.stdout.write("MALFORMED JSON LINE\r\n")
                sys.stdout.write('{"type": "unknown_event_type", "data": 123}\n')
                sys.stdout.write('{"type": "tool_execution_start", "toolName": "edit\u2028line"}\n')
                sys.stdout.flush()

            if scenario == "ui_dialog":
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
                resp_line = sys.stdin.readline()
                if resp_line:
                    resp_obj = json.loads(resp_line.strip())
                    if not resp_obj.get("cancelled"):
                        sys.stderr.write("Expected cancelled=True in UI response\n")

            emit_report_for(message)

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
                json.dumps({"type": "tool_execution_end", "toolName": "edit", "toolCallId": "call-1"}) + "\n"
            )
            sys.stdout.write(json.dumps({"type": "message_start", "delta": "Completed edit\n"}) + "\n")
            sys.stdout.write(json.dumps({"type": "agent_settled"}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
