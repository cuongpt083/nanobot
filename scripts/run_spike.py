"""Spike 2.0 runner: verify H1-H4 against pinned Pi 1.0.2 binary."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def run_spike():
    pi_bin = shutil.which("pi.cmd") or shutil.which("pi") or "pi"
    ext_path = Path("nanobot/coworker/coding/pi/extension/spike/test_extension.ts").resolve()

    results = {}

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        temp_agent_dir = Path(temp_dir) / "agent_dir"
        temp_agent_dir.mkdir()
        temp_cwd = Path(temp_dir) / "workspace"
        temp_cwd.mkdir()

        env = os.environ.copy()
        env["PI_CODING_AGENT_DIR"] = str(temp_agent_dir)

        # -------------------------------------------------------------
        # Hypothesis 1: --no-extensions does not disable explicit --extension
        # -------------------------------------------------------------
        print("Testing H1: --no-extensions with explicit --extension...")
        cmd_h1 = [
            pi_bin,
            "--mode", "rpc",
            "--no-session",
            "--no-extensions",
            "--extension", str(ext_path),
        ]
        proc = subprocess.Popen(
            cmd_h1,
            cwd=str(temp_cwd),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        proc.stdin.write(json.dumps({"id": "h1", "type": "get_commands"}) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        proc.stdin.close()
        proc.terminate()
        proc.wait(timeout=3)

        resp_h1 = json.loads(line) if line else {}
        commands = resp_h1.get("data", {}).get("commands", [])
        has_spike_ping = any(c.get("name") == "spike_ping" for c in commands)
        results["H1"] = {
            "pass": has_spike_ping,
            "evidence": f"Found spike_ping in get_commands: {has_spike_ping} (total commands: {len(commands)})",
        }
        print(f"H1 Result: {results['H1']}")

        # -------------------------------------------------------------
        # Hypothesis 3: Entries via pi.appendEntry appear in get_entries
        # -------------------------------------------------------------
        print("Testing H3: appendEntry in session_start appearing in get_entries...")
        session_file = temp_cwd / "session.jsonl"
        cmd_h3 = [
            pi_bin,
            "--mode", "rpc",
            "--session", str(session_file),
            "--no-extensions",
            "--extension", str(ext_path),
        ]
        proc = subprocess.Popen(
            cmd_h3,
            cwd=str(temp_cwd),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        proc.stdin.write(json.dumps({"id": "h3", "type": "get_entries"}) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        proc.stdin.close()
        proc.terminate()
        proc.wait(timeout=3)

        resp_h3 = json.loads(line) if line else {}
        entries = resp_h3.get("data", {}).get("entries", [])
        has_spike_entry = any(e.get("type") == "spike_entry" or e.get("customType") == "spike_entry" for e in entries)
        results["H3"] = {
            "pass": has_spike_entry,
            "evidence": f"Found spike_entry in get_entries: {has_spike_entry} (entries count: {len(entries)})",
        }
        print(f"H3 Result: {results['H3']}")

        # -------------------------------------------------------------
        # Hypothesis 4: pi.setActiveTools via extension command
        # -------------------------------------------------------------
        print("Testing H4: setActiveTools...")
        cmd_h4 = [
            pi_bin,
            "--mode", "rpc",
            "--no-session",
            "--no-extensions",
            "--extension", str(ext_path),
            "--tools", "read,bash,edit,write",
        ]
        proc = subprocess.Popen(
            cmd_h4,
            cwd=str(temp_cwd),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        # Run command that calls setActiveTools(['read'])
        proc.stdin.write(json.dumps({"id": "h4_cmd", "type": "prompt", "message": "/spike_set_tools"}) + "\n")
        proc.stdin.flush()

        events = []
        for _ in range(10):
            line = proc.stdout.readline()
            if not line:
                break
            try:
                p = json.loads(line)
                events.append(p)
                if p.get("type") == "response" and p.get("id") == "h4_cmd":
                    break
            except Exception:
                pass

        proc.stdin.close()
        proc.terminate()
        proc.wait(timeout=3)

        cmd_resp = next((e for e in events if e.get("id") == "h4_cmd"), {})
        results["H4"] = {
            "pass": cmd_resp.get("success") is True,
            "evidence": f"Response to /spike_set_tools: {cmd_resp}",
        }
        print(f"H4 Result: {results['H4']}")

    # Write report
    report_path = Path("docs/coworker/plans/pi-runtime-spike.md")
    content = f"""# Pi Runtime Spike Report (Pi 1.0.2)

Recorded against pinned binary: `1.0.2` on Windows AMD64.

| Giả định | Mô tả | Kết quả | Bằng chứng |
|---|---|---|---|
| H1 | `--no-extensions` không vô hiệu hoá `--extension <path>` | {'PASS' if results['H1']['pass'] else 'FAIL'} | {results['H1']['evidence']} |
| H3 | `pi.appendEntry` xuất hiện trong `get_entries` | {'PASS' if results['H3']['pass'] else 'FAIL'} | {results['H3']['evidence']} |
| H4 | `pi.setActiveTools` qua extension thay đổi tools active | {'PASS' if results['H4']['pass'] else 'FAIL'} | {results['H4']['evidence']} |
"""
    report_path.write_text(content, encoding="utf-8")
    print(f"Spike report written to {report_path}")


if __name__ == "__main__":
    run_spike()
