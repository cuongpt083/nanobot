"""A stand-in for the bsk CLI, so the nanobot side can be tested without a browser.

It answers the commands the browser package uses with the envelopes bsk 0.3.2 prints (checked against the real
binary). Its behaviour is set by environment variables: FAKE_BSK_START_FAIL, FAKE_BSK_CLAIM_FAIL, FAKE_BSK_HANG.
Every call is appended to FAKE_BSK_LOG as one JSON line, so tests can check the order of calls.
"""

from __future__ import annotations

import json
import os
import sys
import time


def _log(args: list[str]) -> None:
    path = os.environ.get("FAKE_BSK_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(args) + "\n")


def _fail(code: str, message: str, hint: str | None = None) -> int:
    print(json.dumps({"code": code, "message": message, "hint": hint, "exit_code": 1}))
    return 1


def main(argv: list[str]) -> int:
    args = [a for a in argv if a != "--json"]
    _log(args)
    if os.environ.get("FAKE_BSK_HANG") and args[:1] != ["session"]:
        time.sleep(30)
    if args[:2] == ["session", "request"]:
        token, action = args[2], args[3]
        if action == "--prepare":
            print(json.dumps({"request_id": token, "state": "prepared", "session": None, "cleanup_error": None}))
            return 0
        if action == "--claim":
            if os.environ.get("FAKE_BSK_CLAIM_FAIL"):
                return _fail("protocol_error", "request cannot be claimed")
            print(json.dumps({"request_id": token, "state": "active", "session": None, "cleanup_error": None}))
            return 0
    if args[:2] == ["session", "start"]:
        if os.environ.get("FAKE_BSK_START_FAIL"):
            return _fail("no_browser_connected", "no browser is currently connected",
                         "open the browser-skill extension in your browser and wait for the popup")
        token = args[args.index("--request-id") + 1]
        session_id = "s-" + token.split(":", 1)[1][:8]
        print(json.dumps({"session_id": session_id, "browser_instance_id": "b1", "agent_window_id": 7}))
        return 0
    if args == ["session", "list"]:
        print("[]")
        return 0
    if args[:2] == ["session", "stop"]:
        stopped = args[2:3]
        print(json.dumps({"stopped": stopped, "failed": [], "returned_tab_ids": [], "return_failures": []}))
        return 0
    if args and args[0] == "navigate":
        print(json.dumps({"url": args[1], "session": args[3]}))
        return 0
    if args and args[0] in ("observe", "snapshot", "console", "network", "reload",
                            "navigate-back", "navigate-forward", "click", "hover", "fill", "press", "select"):
        print(json.dumps({"command": args[0], "args": args[1:]}))
        return 0
    return _fail("invalid_params", f"unknown command: {' '.join(args)}", "run `bsk <cmd> --help`")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
