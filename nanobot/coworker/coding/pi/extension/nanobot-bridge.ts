import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import * as fs from "fs";
import * as path from "path";

interface ContractData {
  task_id: string;
  mode: "plan" | "implement" | "review";
  root: string;
  write_roots: string[];
  deny_commands: string[];
  deny_read: string[];
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
      pi.setActiveTools(["read", "bash", "ls", "find", "grep", "report_result", "ask_coordinator"]);
    } else {
      // Implement tools
      pi.setActiveTools(["read", "write", "edit", "bash", "ls", "find", "grep", "report_result", "ask_coordinator"]);
    }
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
      const mode = (args.trim() || "implement") as "plan" | "implement" | "review";
      if (contract) {
        contract.mode = mode;
      }
      applyModeTools(mode);
      ctx.ui.notify(`Nanobot mode set to: ${mode}`, "info");
    },
  });

  // Policy enforcement on tool_call
  pi.on("tool_call", async (event, ctx) => {
    if (!contract) return;

    const toolName = event.toolName;
    const args = (event as any).args || {};

    // 1. Guard writes outside write_roots
    if (["write", "edit"].includes(toolName)) {
      if (contract.mode === "plan" || contract.mode === "review") {
        return { block: true, reason: `Write operations disabled in ${contract.mode} mode` };
      }

      const filePath = args.path ? path.resolve(contract.root, args.path) : null;
      if (filePath) {
        const allowed = contract.write_roots.some((root) => {
          const absRoot = path.resolve(root);
          return filePath === absRoot || filePath.startsWith(absRoot + path.sep);
        });
        if (!allowed) {
          ctx.ui.notify(`Write blocked outside write_roots: ${filePath}`, "warning");
          pi.appendEntry("nanobot_block", { type: "write_violation", path: filePath });
          return { block: true, reason: `Path ${filePath} is outside permitted write roots` };
        }
      }
    }

    // 2. Guard dangerous bash commands
    if (toolName === "bash" && typeof args.command === "string") {
      for (const denyPattern of contract.deny_commands || []) {
        const regex = new RegExp(denyPattern, "i");
        if (regex.test(args.command)) {
          ctx.ui.notify(`Command blocked by policy: ${args.command}`, "warning");
          pi.appendEntry("nanobot_block", { type: "command_violation", command: args.command });
          return { block: true, reason: `Command matches deny pattern: ${denyPattern}` };
        }
      }
    }

    // 3. Guard read file
    if (toolName === "read" && typeof args.path === "string") {
      const filePath = path.resolve(contract.root, args.path);
      for (const denyPattern of contract.deny_read || []) {
        if (filePath.includes(denyPattern.replace(/\*/g, ""))) {
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
            properties: { cmd: { type: "string" }, result: { type: "string" }, notes: { type: "string" } },
          },
        },
        plan_steps: { type: "array", items: { type: "string" } },
        verdict: { type: "string", enum: ["pass", "changes_requested"] },
        findings: { type: "array", items: { type: "object" } },
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
    if (!contract || contract.mode !== "implement") return;

    if (!reportSubmitted && continuationsUsed < 1) {
      continuationsUsed++;
      return {
        continue: true,
        message: {
          role: "user",
          content: [{ type: "text", text: "Please call report_result before concluding your implementation." }],
        },
      } as any;
    }
  });
}
