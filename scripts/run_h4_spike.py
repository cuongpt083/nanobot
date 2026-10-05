"""Verify H4: setActiveTools and prompt('/nanobot-mode plan') in RPC mode."""

import json
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path


def run_h4_test():
    pi_bin = shutil.which("pi.cmd") or shutil.which("pi") or "pi"
    ext_path = Path("nanobot/coworker/coding/pi/extension/nanobot-bridge.ts").resolve()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        temp_agent_dir = Path(temp_dir) / "agent_dir"
        temp_agent_dir.mkdir()
        temp_cwd = Path(temp_dir) / "workspace"
        temp_cwd.mkdir()

        # Write dummy contract
        contract_path = Path(temp_dir) / "task-contract.json"
        contract_data = {
            "task_id": "spike-h4",
            "mode": "implement",
            "root": str(temp_cwd),
            "write_roots": [str(temp_cwd)],
            "contract": {
                "objective": "spike h4",
                "context": "",
                "constraints": [],
                "acceptance_criteria": [],
                "acceptance_cmd": "",
                "out_of_scope": [],
                "files": [],
            },
            "settle": {"max_continuations": 1, "acceptance_timeout_s": 30},
            "ask": {"enabled": False},
        }
        contract_path.write_text(json.dumps(contract_data), encoding="utf-8")

        env = os.environ.copy()
        env["PI_CODING_AGENT_DIR"] = str(temp_agent_dir)
        env["NANOBOT_TASK_CONTRACT"] = str(contract_path)

        session_file = temp_cwd / "session.jsonl"
        cmd = [
            pi_bin,
            "--mode", "rpc",
            "--session", str(session_file),
            "--no-extensions",
            "--extension", str(ext_path),
        ]
        proc = subprocess.Popen(
            cmd,
            cwd=str(temp_cwd),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

        stderr_lines = []
        def read_stderr():
            for line in iter(proc.stderr.readline, ''):
                stderr_lines.append(line)

        err_thread = threading.Thread(target=read_stderr, daemon=True)
        err_thread.start()

        try:
            # 1. Switch mode via prompt
            proc.stdin.write(json.dumps({"id": "m1", "type": "prompt", "message": "/nanobot-mode plan"}) + "\n")
            proc.stdin.flush()

            notify_msg = None
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                p = json.loads(line)
                # Check for notify request or response
                if p.get("type") == "extension_ui_request" and p.get("method") == "notify":
                    notify_msg = p.get("message")
                    # respond to ui request if needed
                    resp_id = p.get("id")
                    proc.stdin.write(json.dumps({"id": resp_id, "type": "extension_ui_response", "confirmed": True}) + "\n")
                    proc.stdin.flush()
                if p.get("id") == "m1" and p.get("type") == "response":
                    print("Prompt response:", p)
                    break

            print("Captured notify message:", notify_msg)
            return (
                notify_msg is not None
                and "plan" in notify_msg.lower()
                and "write" not in notify_msg
                and "edit" not in notify_msg
                and "read" in notify_msg
            )
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    ok = run_h4_test()
    print("H4 PASS:", ok)
