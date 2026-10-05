"""Record real Pi RPC transcripts with structural JSON scrubbing."""

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

FIXTURES_DIR = Path("docs/coworker/plans/fixtures/pi-1.x")
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)


def scrub_val(val, known_prefixes: list[tuple[str, str]]):
    if isinstance(val, dict):
        new_d = {}
        for k, v in val.items():
            if k in ("encrypted_content", "textSignature", "thinkingSignature"):
                new_d[k] = "mock_sig"
            elif k in ("responseId", "id") and isinstance(v, str) and re.match(r"^[0-9a-f-]{36}$", v):
                new_d[k] = "00000000-0000-0000-0000-000000000000"
            else:
                new_d[k] = scrub_val(v, known_prefixes)
        return new_d
    elif isinstance(val, list):
        return [scrub_val(item, known_prefixes) for item in val]
    elif isinstance(val, str):
        res = val
        for prefix, rep in known_prefixes:
            res = res.replace(prefix, rep)
        # Scrub generic uuid
        res = re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "00000000-0000-0000-0000-000000000000", res)
        return res
    return val


def run_rpc_session(commands: list[dict], name: str, extra_args: list[str] | None = None, timeout_s: float = 30):
    pi_bin = shutil.which("pi.cmd") or shutil.which("pi") or "pi"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        temp_path = Path(temp_dir)
        (temp_path / "sample.txt").write_text("Hello Pi world\n", encoding="utf-8")

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
            cwd=str(temp_path),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

        known_prefixes = [
            (str(temp_path), "/mock/workspace"),
            (str(Path.home()), "/mock/home"),
            ("C:\\Users\\Admin", "/mock/home"),
            ("C:/Users/Admin", "/mock/home"),
        ]

        stdin_lines = []
        stdout_lines = []

        for c in commands:
            line = json.dumps(c, ensure_ascii=False) + "\n"
            stdin_lines.append(line)
            proc.stdin.write(line)
            proc.stdin.flush()

        import time
        start = time.time()
        while time.time() - start < timeout_s:
            line = proc.stdout.readline()
            if not line:
                break
            try:
                parsed = json.loads(line.strip())
                scrubbed = scrub_val(parsed, known_prefixes)
                stdout_lines.append(json.dumps(scrubbed, ensure_ascii=False) + "\n")
                if scrubbed.get("type") == "agent_settled":
                    break
                if scrubbed.get("type") == "response" and scrubbed.get("success") is False:
                    break
            except Exception as e:
                print("Parse err:", e)

        proc.stdin.close()
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()

        out_dir = FIXTURES_DIR
        (out_dir / f"{name}.stdin.jsonl").write_text("".join(stdin_lines), encoding="utf-8")
        (out_dir / f"{name}.stdout.jsonl").write_text("".join(stdout_lines), encoding="utf-8")
        print(f"Recorded {name}: {len(stdin_lines)} commands, {len(stdout_lines)} output events")


if __name__ == "__main__":
    # 1. Success with tool (read file)
    print("Recording 1: success with tool...")
    run_rpc_session([
        {"id": "c1", "type": "prompt", "message": "Read sample.txt and report the content in 3 words."}
    ], "01-success-tool", ["--tools", "read,ls"], timeout_s=25)

    # 2. Rejected command (set_model with invalid model)
    print("Recording 2: rejected command (invalid model)...")
    run_rpc_session([
        {"id": "c2", "type": "set_model", "model": "invalid_provider/fake_model"}
    ], "02-rejected-command", timeout_s=10)

    # 3. Compaction
    print("Recording 3: compaction...")
    run_rpc_session([
        {"id": "c3_1", "type": "prompt", "message": "Say Hi"},
        {"id": "c3_2", "type": "compact"}
    ], "03-compaction", timeout_s=25)

    # 4. Abort mid-run
    print("Recording 4: abort...")
    run_rpc_session([
        {"id": "c4_1", "type": "prompt", "message": "Write a 500 word story about cats"},
        {"id": "c4_2", "type": "abort"}
    ], "04-abort", timeout_s=25)
