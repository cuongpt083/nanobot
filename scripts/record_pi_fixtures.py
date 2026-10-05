"""Record real Pi RPC transcripts for fixtures."""

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

FIXTURES_DIR = Path("docs/coworker/plans/fixtures/pi-1.x")
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

SCRUB_PATTERNS = [
    (re.compile(r"C:\\\\[a-zA-Z0-9_\\\.\-]+"), "/mock/path"),
    (re.compile(r"C:/[a-zA-Z0-9_/\\.\-]+"), "/mock/path"),
    (re.compile(r"\"encrypted_content\":\s*\"[^\"]+\""), '"encrypted_content": "mock_encrypted"'),
    (re.compile(r"\"textSignature\":\s*\"[^\"]+\""), '"textSignature": "mock_sig"'),
    (re.compile(r"\"thinkingSignature\":\s*\"[^\"]+\""), '"thinkingSignature": "mock_sig"'),
    (re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"), "00000000-0000-0000-0000-000000000000"),
]

def scrub_line(text: str) -> str:
    for pat, rep in SCRUB_PATTERNS:
        text = pat.sub(rep, text)
    return text


def run_rpc_session(commands: list[dict], name: str, extra_args: list[str] | None = None, wait_events: int = 15):
    pi_bin = shutil.which("pi.cmd") or shutil.which("pi") or "pi"
    cmd = [
        pi_bin,
        "--mode", "rpc",
        "--no-session",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        "--no-themes",
    ]
    if extra_args:
        cmd.extend(extra_args)

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )

    stdin_lines = []
    stdout_lines = []

    for c in commands:
        line = json.dumps(c, ensure_ascii=False) + "\n"
        stdin_lines.append(line)
        proc.stdin.write(line)
        proc.stdin.flush()

    for _ in range(wait_events):
        line = proc.stdout.readline()
        if not line:
            break
        stdout_lines.append(line)
        try:
            parsed = json.loads(line)
            if parsed.get("type") == "agent_settled":
                break
            if parsed.get("type") == "response" and parsed.get("success") is False:
                break
        except Exception:
            pass

    proc.stdin.close()
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except Exception:
        proc.kill()

    out_dir = FIXTURES_DIR
    (out_dir / f"{name}.stdin.jsonl").write_text("".join([scrub_line(l) for l in stdin_lines]), encoding="utf-8")
    (out_dir / f"{name}.stdout.jsonl").write_text("".join([scrub_line(l) for l in stdout_lines]), encoding="utf-8")
    print(f"Recorded {name}: {len(stdin_lines)} commands, {len(stdout_lines)} output events")


if __name__ == "__main__":
    # 1. Success with tool
    print("Recording 1: success with tool...")
    run_rpc_session([
        {"id": "c1", "type": "prompt", "message": "List files in the current folder using read or ls tool."}
    ], "01-success-tool", ["--tools", "read,ls,find,grep"])

    # 2. Refused / error prompt (empty or invalid command)
    print("Recording 2: prompt error / invalid command...")
    run_rpc_session([
        {"id": "c2", "type": "non_existent_command", "message": "invalid"}
    ], "02-rejected-command")

    # 3. Compaction
    print("Recording 3: compaction...")
    run_rpc_session([
        {"id": "c3_1", "type": "prompt", "message": "Say hello in one word"},
        {"id": "c3_2", "type": "compact"}
    ], "03-compaction")

    # 4. Abort mid-run
    print("Recording 4: abort...")
    run_rpc_session([
        {"id": "c4_1", "type": "prompt", "message": "Write a long essay about space"},
        {"id": "c4_2", "type": "abort"}
    ], "04-abort")
