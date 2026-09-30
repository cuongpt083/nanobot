"""Fake agy CLI for testing AgyBackend without external network or binaries."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-p", "--print", "--prompt", dest="prompt", default="")
    parser.add_argument("--output-format", default="text")
    parser.add_argument("--input-format", default="text")
    parser.add_argument("--conversation", default=None)
    parser.add_argument("--dangerously-skip-permissions", action="store_true")
    parser.add_argument("--sandbox", action="store_true")
    parser.add_argument("--mode", default=None)
    parser.add_argument("--print-timeout", default="0s")

    args, extra = parser.parse_known_args()

    # Read stdin if input-format is stream-json and prompt is empty
    if args.input_format == "stream-json" and not args.prompt:
        try:
            line = sys.stdin.readline()
            if line:
                data = json.loads(line)
                args.prompt = data.get("message", {}).get("content", "")
        except Exception:
            pass

    scenario = os.environ.get("FAKE_AGY_SCENARIO", "").strip()

    if scenario == "hang":
        time.sleep(300)
        sys.exit(0)

    if scenario.startswith("exit_code:"):
        code = int(scenario.split(":", 1)[1])
        sys.stderr.write(f"fake_agy error: exited with code {code}\n")
        sys.exit(code)

    if scenario.startswith("write_file:"):
        # Format: write_file:path:content
        _, fpath, content = scenario.split(":", 2)
        target = Path(fpath)
        if not target.is_absolute():
            target = Path.cwd() / target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    conv_id = args.conversation or "fake-agy-conv-12345"

    if scenario.startswith("fixture:"):
        fixture_name = scenario.split(":", 1)[1]
        fixtures_dir = Path(__file__).parent / "fixtures" / "agy-1.2.13"
        fpath = fixtures_dir / fixture_name
        if not fpath.exists():
            fpath = Path(fixture_name)
        if fpath.exists():
            for line in fpath.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
            sys.exit(0)

    if scenario == "missing_result":
        sys.stdout.write(
            json.dumps({"event": "init", "conversation_id": conv_id, "init": {"cwd": os.getcwd()}})
            + "\n"
        )
        sys.stdout.write(
            json.dumps({
                "event": "step_update",
                "step_update": {"conversation_id": conv_id, "step_index": 0, "state": "DONE", "step_type": "user_input"},
            })
            + "\n"
        )
        sys.stdout.flush()
        sys.exit(0)

    if scenario == "status_error":
        sys.stdout.write(
            json.dumps({"event": "init", "conversation_id": conv_id, "init": {"cwd": os.getcwd()}})
            + "\n"
        )
        sys.stdout.write(
            json.dumps({
                "event": "result",
                "result": {
                    "conversation_id": conv_id,
                    "status": "FAILED",
                    "error": "syntax error during code generation",
                    "response": "",
                    "duration_seconds": 1.0,
                    "num_turns": 1,
                    "usage": {"input_tokens": 100, "output_tokens": 10, "thinking_tokens": 0, "cache_read_tokens": 0, "total_tokens": 110},
                },
            })
            + "\n"
        )
        sys.stdout.flush()
        sys.exit(0)

    # Default / standard success output
    sys.stdout.write(
        json.dumps({"event": "init", "conversation_id": conv_id, "init": {"cwd": os.getcwd(), "tools": ["write_to_file", "run_command"], "permission_mode": "always-proceed"}})
        + "\n"
    )
    sys.stdout.write(
        json.dumps({
            "event": "step_update",
            "step_update": {
                "conversation_id": conv_id,
                "step_index": 1,
                "state": "ACTIVE",
                "step_type": "tool",
                "tool_name": "write_to_file",
                "tool_info": {"name": "write_to_file", "parameters": {"TargetFile": "test.txt"}},
            },
        })
        + "\n"
    )
    sys.stdout.write(
        json.dumps({
            "event": "step_update",
            "step_update": {
                "conversation_id": conv_id,
                "step_index": 1,
                "state": "DONE",
                "step_type": "tool",
                "tool_name": "write_to_file",
                "tool_info": {"name": "write_to_file", "parameters": {"TargetFile": "test.txt"}},
            },
        })
        + "\n"
    )
    sys.stdout.write(
        json.dumps({
            "event": "step_update",
            "step_update": {
                "conversation_id": conv_id,
                "step_index": 2,
                "state": "DONE",
                "step_type": "agent_response",
                "text_delta": "Changes applied successfully.\n",
            },
        })
        + "\n"
    )
    # If this is a resumed run with an existing conversation_id, simulate higher cumulative usage
    cumulative_base = 5000 if args.conversation else 0
    sys.stdout.write(
        json.dumps({
            "event": "result",
            "result": {
                "conversation_id": conv_id,
                "status": "SUCCESS",
                "response": "Changes applied successfully.\n",
                "duration_seconds": 2.5,
                "num_turns": 2 if args.conversation else 1,
                "usage": {
                    "input_tokens": cumulative_base + 1200,
                    "output_tokens": 150,
                    "thinking_tokens": 50,
                    "cache_read_tokens": 0,
                    "total_tokens": cumulative_base + 1400,
                },
            },
        })
        + "\n"
    )
    sys.stdout.flush()


if __name__ == "__main__":
    main()
