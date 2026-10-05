"""Verify H2: agent_before_settle continue: true with mock provider."""

import json
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path


def run_h2_test():
    pi_bin = shutil.which("pi.cmd") or shutil.which("pi") or "pi"
    ext_path = Path("nanobot/coworker/coding/pi/extension/spike/test_h2.ts").resolve()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        temp_agent_dir = Path(temp_dir) / "agent_dir"
        temp_agent_dir.mkdir()
        temp_cwd = Path(temp_dir) / "workspace"
        temp_cwd.mkdir()

        env = os.environ.copy()
        env["PI_CODING_AGENT_DIR"] = str(temp_agent_dir)

        session_file = temp_cwd / "session.jsonl"
        cmd = [
            pi_bin,
            "--mode", "rpc",
            "--session", str(session_file),
            "--provider", "mock-provider",
            "--model", "mock-model",
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

        events = []
        stderr_lines = []

        def read_stderr():
            for line in iter(proc.stderr.readline, ''):
                stderr_lines.append(line)

        err_thread = threading.Thread(target=read_stderr, daemon=True)
        err_thread.start()

        try:
            # 1. Send prompt
            proc.stdin.write(json.dumps({"id": "p1", "type": "prompt", "message": "hello"}) + "\n")
            proc.stdin.flush()

            # 2. Read events until agent_settled
            turn_starts = 0
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                p = json.loads(line)
                events.append(p)
                p_type = p.get("type")
                if p_type == "turn_start":
                    turn_starts += 1
                    print(f"Saw turn_start #{turn_starts}")
                elif p_type == "agent_settled":
                    print("Saw agent_settled!")
                    break
                elif p_type == "response" and not p.get("success"):
                    print(f"Error response: {p}")
                    break

            # 3. Query entries
            proc.stdin.write(json.dumps({"id": "ent", "type": "get_entries"}) + "\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
            resp_ent = json.loads(line) if line else {}
            entries = resp_ent.get("data", {}).get("entries", [])
            h2_entries = [e for e in entries if e.get("type") == "h2_continuation" or e.get("customType") == "h2_continuation"]

            print(f"H2 continuation entries: {len(h2_entries)}, turn_starts: {turn_starts}")
            return len(h2_entries) == 2 and turn_starts == 3
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
            if stderr_lines:
                print("STDERR:", "".join(stderr_lines[:10]))


if __name__ == "__main__":
    ok = run_h2_test()
    print("H2 PASS:", ok)
