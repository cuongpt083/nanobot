"""Integration tests for nanobot-bridge.ts extension policies running on real Pi with mock provider."""

import json
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import pytest


PI_CMD = shutil.which("pi.cmd") or shutil.which("pi")


@pytest.mark.skipif(not PI_CMD, reason="Pi executable not found on system")
def test_bridge_policy_enforcement():
    bridge_path = Path(__file__).resolve().parents[3] / "nanobot" / "coworker" / "coding" / "pi" / "extension" / "nanobot-bridge.ts"
    assert bridge_path.exists()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        temp_agent_dir = Path(temp_dir) / "agent_dir"
        temp_agent_dir.mkdir()
        temp_cwd = Path(temp_dir) / "workspace"
        temp_cwd.mkdir()

        secret_file = Path(temp_dir) / "secret.env"
        secret_file.write_text("API_SECRET=12345", encoding="utf-8")

        contract_path = Path(temp_dir) / "task-contract.json"
        contract_data = {
            "task_id": "test-policy",
            "mode": "implement",
            "root": str(temp_cwd),
            "write_roots": [str(temp_cwd)],
            "deny_commands": ["^git\\s+push", "^git\\s+remote"],
            "deny_read": ["**/.env*", "*.env*"],
            "contract": {
                "objective": "test policy",
                "context": "testing policies",
                "acceptance_criteria": [],
                "acceptance_cmd": "",
                "out_of_scope": [],
                "files": [],
            },
            "settle": {"max_continuations": 1, "acceptance_timeout_s": 30},
            "ask": {"enabled": False},
        }
        contract_path.write_text(json.dumps(contract_data), encoding="utf-8")

        mock_ext_path = Path(temp_dir) / "mock_driver.ts"
        mock_ext_path.write_text("""
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { createAssistantMessageEventStream } from "@earendil-works/pi-ai";

export default function (pi: ExtensionAPI) {
  let step = 0;

  pi.registerProvider("test-provider", {
    baseUrl: "https://mock.local",
    apiKey: "mock-key",
    api: "mock-api",
    models: [
      {
        id: "test-model",
        name: "Test Model",
        reasoning: false,
        input: ["text"],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 100000,
        maxTokens: 4000,
      },
    ],
    streamSimple: (_model: any, context: any, _options: any) => {
      const stream = createAssistantMessageEventStream();
      step++;

      let toolCalls: any[] = [];
      if (step === 1) {
        toolCalls = [{ id: "call-1", name: "write", arguments: { path: "../outside.txt", content: "forbidden" } }];
      } else if (step === 2) {
        toolCalls = [{ id: "call-2", name: "bash", arguments: { command: "git push origin main" } }];
      } else if (step === 3) {
        toolCalls = [{ id: "call-3", name: "powershell", arguments: { command: "git push origin main" } }];
      } else if (step === 4) {
        toolCalls = [{ id: "call-4", name: "read", arguments: { path: "../secret.env" } }];
      } else if (step === 5) {
        toolCalls = [{
          id: "call-5",
          name: "report_result",
          arguments: {
            kind: "implementation",
            status: "done",
            summary: "Policy tests completed",
          },
        }];
      } else {
        toolCalls = [];
      }

      const isToolUse = toolCalls.length > 0;
      const content = isToolUse
        ? toolCalls.map(tc => ({ type: "toolCall", id: tc.id, name: tc.name, arguments: tc.arguments }))
        : [{ type: "text", text: "Done" }];

      const fullMessage = {
        role: "assistant",
        content,
        api: "mock-api",
        provider: "test-provider",
        model: "test-model",
        usage: { input: 10, output: 10, cacheRead: 0, cacheWrite: 0, totalTokens: 20, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
        stopReason: isToolUse ? "toolUse" : "stop",
        timestamp: Date.now(),
      };

      setTimeout(() => {
        const partial = { ...fullMessage, content: [], stopReason: "pending" };
        stream.push({ type: "start", partial: { ...partial } });

        for (let i = 0; i < content.length; i++) {
          const block = content[i];
          if (block.type === "toolCall") {
            partial.content = [...partial.content, { type: "toolCall", id: block.id, name: block.name, arguments: {} }];
            stream.push({ type: "toolcall_start", contentIndex: i, partial: { ...partial } });
            partial.content[i].arguments = block.arguments;
            stream.push({ type: "toolcall_delta", contentIndex: i, delta: JSON.stringify(block.arguments), partial: { ...partial } });
            stream.push({ type: "toolcall_end", contentIndex: i, toolCall: block, partial: { ...partial } });
          } else {
            partial.content = [...partial.content, { type: "text", text: block.text }];
            stream.push({ type: "text_start", contentIndex: i, partial: { ...partial } });
            stream.push({ type: "text_end", contentIndex: i, content: block.text, partial: { ...partial } });
          }
        }

        stream.push({ type: "done", reason: fullMessage.stopReason, message: fullMessage as any });
        stream.end(fullMessage as any);
      }, 10);

      return stream;
    },
  });
}
""", encoding="utf-8")

        cmd = [
            PI_CMD,
            "--mode", "rpc",
            "--no-session",
            "--provider", "test-provider",
            "--model", "test-model",
            "--extension", str(mock_ext_path),
            "--extension", str(bridge_path),
        ]
        env = dict(
            PATH=shutil.which("node") or "",
            PI_CODING_AGENT_DIR=str(temp_agent_dir),
            NANOBOT_TASK_CONTRACT=str(contract_path),
            USERPROFILE=temp_dir,
            APPDATA=temp_dir,
            LOCALAPPDATA=temp_dir,
            SystemRoot=shutil.which("cmd.exe") or "C:\\Windows",
        )
        import os
        for k in ("PATH", "APPDATA", "LOCALAPPDATA", "USERPROFILE", "SystemRoot", "TEMP", "TMP"):
            if k in os.environ:
                env[k] = os.environ[k]

        proc = subprocess.Popen(
            cmd,
            cwd=str(temp_cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        entries_captured = []
        settled = False

        def read_stdout():
            nonlocal settled
            for line in proc.stdout:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    ev = json.loads(line_str)
                    if ev.get("type") == "agent_settled":
                        settled = True
                    if ev.get("type") == "response" and ev.get("command") == "get_entries":
                        for item in ev.get("data", {}).get("entries", []):
                            entries_captured.append(item)
                except Exception:
                    pass

        t = threading.Thread(target=read_stdout, daemon=True)
        t.start()

        # Prompt run
        prompt_cmd = json.dumps({"id": "p1", "type": "prompt", "message": "Execute test actions"}) + "\n"
        proc.stdin.write(prompt_cmd)
        proc.stdin.flush()

        import time
        start_wait = time.time()
        while not settled and time.time() - start_wait < 30:
            time.sleep(0.1)

        assert settled is True

        # Fetch entries
        entries_cmd = json.dumps({"id": "get_e", "type": "get_entries"}) + "\n"
        proc.stdin.write(entries_cmd)
        proc.stdin.flush()

        time.sleep(1.0)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

        blocks = [e for e in entries_captured if e.get("customType") == "nanobot_block"]
        assert len(blocks) == 4
        block_types = [b.get("data", {}).get("type") for b in blocks]
        assert "write_violation" in block_types
        assert "command_violation" in block_types
        assert "read_violation" in block_types

        reports = [e for e in entries_captured if e.get("customType") == "nanobot_report"]
        assert len(reports) >= 1
