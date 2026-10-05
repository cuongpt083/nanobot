import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import * as child_process from "child_process";
import * as fs from "fs";
import * as path from "path";

interface ContractData {
  task_id: string;
  mode: "plan" | "implement" | "review";
  root: string;
  write_roots: string[];
  deny_commands?: string[];
  deny_read?: string[];
  contract?: {
    objective?: string;
    context?: string;
    constraints?: string[];
    acceptance_criteria?: string[];
    acceptance_cmd?: string;
    out_of_scope?: string[];
    files?: string[];
  };
  plan?: string;
  settle?: {
    max_continuations?: number;
    acceptance_timeout_s?: number;
  };
  ask?: {
    enabled?: boolean;
  };
}

export default function (pi: ExtensionAPI) {
  let contract: ContractData | null = null;
  let continuationsUsed = 0;
  let reportSubmitted = false;

  function loadContract(): void {
    const contractEnv = process.env.NANOBOT_TASK_CONTRACT;
    if (contractEnv && fs.existsSync(contractEnv)) {
      try {
        const raw = fs.readFileSync(contractEnv, "utf-8");
        contract = JSON.parse(raw);
      } catch (e) {
        // Fallback or ignore
      }
    }
  }

  function applyModeTools(mode: "plan" | "implement" | "review"): void {
    if (mode === "plan" || mode === "review") {
      // Read-only tools
      pi.setActiveTools([
        "read",
        "bash",
        "powershell",
        "ls",
        "find",
        "grep",
        "report_result",
        "ask_coordinator",
      ]);
    } else {
      // Implement tools
      pi.setActiveTools([
        "read",
        "write",
        "edit",
        "bash",
        "powershell",
        "ls",
        "find",
        "grep",
        "report_result",
        "ask_coordinator",
      ]);
    }
  }

  function normalizePathForComparison(p: string): string {
    const resolved = path.resolve(p);
    return process.platform === "win32" ? resolved.toLowerCase() : resolved;
  }

  function isPathWithin(target: string, parent: string): boolean {
    const normTarget = normalizePathForComparison(target);
    const normParent = normalizePathForComparison(parent);
    if (normTarget === normParent) return true;
    return normTarget.startsWith(normParent.endsWith(path.sep) ? normParent : normParent + path.sep);
  }

  pi.on("session_start", async () => {
    loadContract();
    if (contract) {
      applyModeTools(contract.mode);
    }
  });

  // /nanobot-mode command
  pi.registerCommand("nanobot-mode", {
    description: "Switch nanobot operation mode (plan, implement, review)",
    handler: async (args, ctx) => {
      loadContract();
      const mode = (args.trim() || (contract ? contract.mode : "implement")) as
        | "plan"
        | "implement"
        | "review";
      if (contract) {
        contract.mode = mode;
      }
      applyModeTools(mode);
      const active = pi.getActiveTools();
      ctx.ui.notify(`Nanobot mode set to: ${mode}; active_tools: ${active.join(",")}`, "info");
    },
  });

  // Inject system prompt sections via before_agent_start
  pi.on("before_agent_start", async (event) => {
    loadContract();
    if (!contract) return;

    const sections = event.systemPromptOptions.sections || {};

    if (contract.contract) {
      const c = contract.contract;
      sections["nanobot_task"] = [
        `Objective: ${c.objective || ""}`,
        `Context: ${c.context || ""}`,
        `Constraints: ${(c.constraints || []).join("; ")}`,
        `Out of scope: ${(c.out_of_scope || []).join("; ")}`,
      ].join("\n");

      if (c.acceptance_criteria || c.acceptance_cmd) {
        sections["nanobot_acceptance"] = [
          `Criteria: ${(c.acceptance_criteria || []).join("; ")}`,
          `Command: ${c.acceptance_cmd || "none"}`,
        ].join("\n");
      }
    }

    if (contract.plan) {
      sections["nanobot_plan"] = contract.plan;
    }

    sections["nanobot_mode"] = [
      `Current Mode: ${contract.mode}`,
      `Instruction: You are in ${contract.mode} mode. Conclude your work with report_result tool call.`,
    ].join("\n");

    event.systemPromptOptions.sections = sections;
  });

  // Progress update on turn_end
  pi.on("turn_end", async (event, ctx) => {
    try {
      ctx.ui.setStatus("nanobot", `Turn ${event.turnIndex + 1} completed`);
    } catch {
      // ignore
    }
  });

  // Policy enforcement on tool_call
  pi.on("tool_call", async (event, ctx) => {
    loadContract();
    if (!contract) return;

    const toolName = event.toolName;
    const args = (event as any).input || (event as any).args || {};

    // 1. Guard writes outside write_roots
    if (["write", "edit"].includes(toolName)) {
      if (contract.mode === "plan" || contract.mode === "review") {
        return { block: true, reason: `Write operations disabled in ${contract.mode} mode` };
      }

      const filePath = args.path
        ? path.isAbsolute(args.path)
          ? args.path
          : path.resolve(contract.root, args.path)
        : null;

      if (filePath) {
        const allowed = (contract.write_roots || []).some((root) => isPathWithin(filePath, root));
        if (!allowed) {
          ctx.ui.notify(`Write blocked outside write_roots: ${filePath}`, "warning");
          pi.appendEntry("nanobot_block", { type: "write_violation", path: filePath });
          return { block: true, reason: `Path ${filePath} is outside permitted write roots` };
        }
      }
    }

    // 2. Guard dangerous shell/bash/powershell commands
    if (["bash", "powershell"].includes(toolName)) {
      const command = (typeof args.command === "string" ? args.command : args.cmd) || "";
      if (typeof command === "string") {
        for (const denyPattern of contract.deny_commands || []) {
          try {
            const regex = new RegExp(denyPattern, "i");
            if (regex.test(command)) {
              ctx.ui.notify(`Command blocked by policy: ${command}`, "warning");
              pi.appendEntry("nanobot_block", { type: "command_violation", command });
              return { block: true, reason: `Command matches deny pattern: ${denyPattern}` };
            }
          } catch {
            // regex compilation fallback
            if (command.toLowerCase().includes(denyPattern.toLowerCase())) {
              ctx.ui.notify(`Command blocked by policy: ${command}`, "warning");
              pi.appendEntry("nanobot_block", { type: "command_violation", command });
              return { block: true, reason: `Command matches deny pattern: ${denyPattern}` };
            }
          }
        }
      }
    }

    // 3. Guard read file
    if (toolName === "read" && typeof args.path === "string") {
      const filePath = path.isAbsolute(args.path)
        ? path.resolve(args.path)
        : path.resolve(contract.root, args.path);

      for (const denyPattern of contract.deny_read || []) {
        const cleanPattern = denyPattern.replace(/\*/g, "");
        if (filePath.includes(cleanPattern)) {
          ctx.ui.notify(`Read blocked by policy: ${filePath}`, "warning");
          pi.appendEntry("nanobot_block", { type: "read_violation", path: filePath });
          return { block: true, reason: `Path matches deny read pattern: ${denyPattern}` };
        }
      }
    }
  });

  // Register report_result tool
  pi.registerTool({
    name: "report_result",
    description: "Submit final structured report for the phase (plan, implementation, or review)",
    parameters: {
      type: "object",
      required: ["kind", "status", "summary"],
      properties: {
        kind: { type: "string", enum: ["plan", "implementation", "review"] },
        status: { type: "string", enum: ["done", "partial", "blocked"] },
        summary: { type: "string" },
        changes: {
          type: "array",
          items: {
            type: "object",
            required: ["path", "what"],
            properties: { path: { type: "string" }, what: { type: "string" } },
          },
        },
        tests_run: {
          type: "array",
          items: {
            type: "object",
            required: ["cmd", "result"],
            properties: {
              cmd: { type: "string" },
              result: { type: "string" },
              notes: { type: "string" },
            },
          },
        },
        plan_steps: { type: "array", items: { type: "string" } },
        test_plan: { type: "array", items: { type: "string" } },
        verdict: { type: "string", enum: ["pass", "changes_requested"] },
        findings: {
          type: "array",
          items: {
            type: "object",
            properties: {
              severity: { type: "string", enum: ["blocking", "major", "minor"] },
              file: { type: "string" },
              line: { type: "number" },
              issue: { type: "string" },
              fix: { type: "string" },
            },
          },
        },
        risks: { type: "array", items: { type: "string" } },
        open_questions: { type: "array", items: { type: "string" } },
      },
    },
    execute: async (_toolCallId, params) => {
      reportSubmitted = true;
      pi.appendEntry("nanobot_report", params);
      return {
        content: [{ type: "text", text: `Report submitted successfully: ${params.status}` }],
        details: params,
      };
    },
  });

  // Register ask_coordinator tool
  pi.registerTool({
    name: "ask_coordinator",
    description: "Ask the nanobot coordinator a blocking question",
    parameters: {
      type: "object",
      required: ["question", "blocking_reason"],
      properties: {
        question: { type: "string" },
        blocking_reason: { type: "string" },
        options: { type: "array", items: { type: "string" } },
      },
    },
    execute: async (_toolCallId, params, _signal, _onUpdate, ctx) => {
      loadContract();
      if (contract?.ask?.enabled === false) {
        return {
          content: [
            {
              type: "text",
              text: "Không có kênh hỏi trong chế độ chờ đồng bộ; chọn giả định an toàn nhất, ghi vào open_questions.",
            },
          ],
          details: { answered: false, reason: "ask_disabled" },
        };
      }

      const title = `nanobot:ask:${params.blocking_reason}`;
      try {
        let answer = "";
        if (params.options && params.options.length > 0) {
          answer = await ctx.ui.select(title, params.options);
        } else {
          answer = await ctx.ui.input(title, params.question);
        }
        return {
          content: [{ type: "text", text: `Coordinator answer: ${answer}` }],
          details: { answered: true, answer },
        };
      } catch (err) {
        return {
          content: [
            {
              type: "text",
              text: "Không có trả lời; chọn giả định an toàn nhất, ghi vào open_questions của report.",
            },
          ],
          details: { answered: false, error: String(err) },
        };
      }
    },
  });

  // Acceptance & gate via agent_before_settle
  pi.on("agent_before_settle", async () => {
    loadContract();
    if (!contract || contract.mode !== "implement") {
      return { continue: false };
    }

    const maxContinuations = contract.settle?.max_continuations ?? 2;

    // 1. Report result check
    if (!reportSubmitted && continuationsUsed < 1) {
      continuationsUsed++;
      pi.appendEntry("nanobot_gate", {
        passed: false,
        reason: "missing_report_result",
        continuations_used: continuationsUsed,
      });
      return {
        continue: true,
        entries: [
          {
            type: "custom_message",
            customType: "continuation_prompt",
            content: "Please call report_result before concluding your implementation.",
            display: true,
          } as any,
        ],
      };
    }

    // 2. Acceptance cmd check
    const acceptanceCmd = contract.contract?.acceptance_cmd;
    let acceptancePassed = false;
    if (acceptanceCmd && continuationsUsed < maxContinuations) {
      try {
        const timeoutMs = (contract.settle?.acceptance_timeout_s ?? 600) * 1000;
        child_process.execSync(acceptanceCmd, {
          cwd: contract.root,
          timeout: timeoutMs,
          stdio: ["ignore", "pipe", "pipe"],
        });
        acceptancePassed = true;
        pi.appendEntry("nanobot_gate", { passed: true, continuations_used: continuationsUsed });
        return { continue: false };
      } catch (error: any) {
        continuationsUsed++;
        const output = (error.stdout ? error.stdout.toString() : "") +
                       (error.stderr ? error.stderr.toString() : error.message || "");
        const truncatedOutput = output.slice(-4000);

        if (continuationsUsed <= maxContinuations) {
          return {
            continue: true,
            entries: [
              {
                type: "custom_message",
                customType: "continuation_prompt",
                content: `Acceptance command failed:\n\`\`\`\n${truncatedOutput}\n\`\`\`\nPlease fix the issues and rerun your tests.`,
                display: true,
              } as any,
            ],
          };
        }
      }
    }

    pi.appendEntry("nanobot_gate", {
      passed: !acceptanceCmd || acceptancePassed,
      continuations_used: continuationsUsed,
    });
    return { continue: false };
  });
}
