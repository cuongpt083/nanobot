"""Verify nanobot-bridge.ts policy enforcement using a scripted mock provider."""

import json
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path


def run_bridge_policy_test():
    pi_bin = shutil.which("pi.cmd") or shutil.which("pi") or "pi"
    bridge_path = Path("nanobot/coworker/coding/pi/extension/nanobot-bridge.ts").resolve()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
        temp_agent_dir = Path(temp_dir) / "agent_dir"
        temp_agent_dir.mkdir()
        temp_cwd = Path(temp_dir) / "workspace"
        temp_cwd.mkdir()

        # Secret outside workspace
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

        # Mock script extension that defines a mock model using exact pi-ai event stream contract
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
        // Attempt 1: write outside write_roots
        toolCalls = [{ id: "call-1", name: "write", arguments: { path: "../outside.txt", content: "forbidden" } }];
      } else if (step === 2) {
        // Attempt 2: git push via bash
        toolCalls = [{ id: "call-2", name: "bash", arguments: { command: "git push origin main" } }];
      } else if (step === 3) {
        // Attempt 3: git push via powershell
        toolCalls = [{ id: "call-3", name: "powershell", arguments: { command: "git push origin main" } }];
      } else if (step === 4) {
        // Attempt 4: read denied pattern
        toolCalls = [{ id: "call-4", name: "read", arguments: { path: "../secret.env" } }];
      } else if (step === 5) {
        // Submit report
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
        // Plain text done - stop calling tools
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

        env = os.environ.copy()
        env["PI_CODING_AGENT_DIR"] = str(temp_agent_dir)
        env["NANOBOT_TASK_CONTRACT"] = str(contract_path)

        session_file = temp_cwd / "session.jsonl"
        cmd = [
            pi_bin,
            "--mode", "rpc",
            "--session", str(session_file),
            "--provider", "test-provider",
            "--model", "test-model",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--extension", str(mock_ext_path),
            "--extension", str(bridge_path),
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

        events = []
        def read_stdout():
            for line in iter(proc.stdout.readline, ''):
                try:
                    events.append(json.loads(line))
                except Exception:
                    pass

        out_thread = threading.Thread(target=read_stdout, daemon=True)
        out_thread.start()

        try:
            # Send initial prompt
            proc.stdin.write(json.dumps({"id": "p1", "type": "prompt", "message": "run policy tests"}) + "\n")
            proc.stdin.flush()

            import time
            start = time.time()
            settled = False
            while time.time() - start < 15:
                if any(ev.get("type") == "agent_settled" for ev in events):
                    settled = True
                    break
                time.sleep(0.1)

            print(f"Settled: {settled}, total events captured: {len(events)}")
            extension_errors = [e for e in events if e.get("type") == "extension_error"]

            # Fetch entries
            proc.stdin.write(json.dumps({"id": "ent", "type": "get_entries"}) + "\n")
            proc.stdin.flush()

            # Wait for response with id ent
            resp_ent = None
            ent_start = time.time()
            while time.time() - ent_start < 5:
                resp = next((e for e in events if e.get("id") == "ent" and e.get("type") == "response"), None)
                if resp:
                    resp_ent = resp
                    break
                time.sleep(0.1)

            entries = (resp_ent or {}).get("data", {}).get("entries", [])
            block_entries = [e for e in entries if e.get("type") == "nanobot_block" or e.get("customType") == "nanobot_block"]
            report_entries = [e for e in entries if e.get("type") == "nanobot_report" or e.get("customType") == "nanobot_report"]

            print(f"Extension errors: {len(extension_errors)} -> {extension_errors}")
            print(f"Blocked violations caught: {len(block_entries)} -> {block_entries}")
            print(f"Report entries: {len(report_entries)}")

            # Assertions
            assert len(extension_errors) == 0, f"Unexpected extension errors: {extension_errors}"
            assert len(block_entries) == 4, f"Expected 4 blocked entries, found {len(block_entries)}"
            assert len(report_entries) == 1, f"Expected 1 report entry, found {len(report_entries)}"
            return True
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
    ok = run_bridge_policy_test()
    print("BRIDGE POLICY TEST PASS:", ok)
