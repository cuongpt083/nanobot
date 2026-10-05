import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  let continuations = 0;

  pi.registerCommand("spike_ping", {
    description: "Ping command to verify explicit extension loading",
    handler: async (_args, ctx) => {
      ctx.ui.notify("pong", "info");
    },
  });

  pi.registerCommand("spike_set_tools", {
    description: "Test setActiveTools",
    handler: async (_args, ctx) => {
      pi.setActiveTools(["read"]);
      ctx.ui.notify(`Active tools now: ${pi.getActiveTools().join(",")}`, "info");
    },
  });

  pi.on("session_start", async (_event, _ctx) => {
    pi.appendEntry("spike_entry", { key: "spike_val_123" });
  });

  pi.on("agent_before_settle", async (_event, _ctx) => {
    if (continuations < 1) {
      continuations++;
      pi.appendEntry("spike_continue", { count: continuations });
      // In Pi extensions, continuing with a message:
      return {
        continue: true,
        message: {
          role: "user",
          content: [{ type: "text", text: "Continue turn for spike verification" }],
        },
      } as any;
    }
  });
}
