import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { createAssistantMessageEventStream } from "@earendil-works/pi-ai";

export default function (pi: ExtensionAPI) {
  let continuations = 0;

  pi.registerProvider("mock-provider", {
    baseUrl: "https://mock.local",
    apiKey: "mock-key",
    api: "mock-api",
    models: [
      {
        id: "mock-model",
        name: "Mock Model",
        reasoning: false,
        input: ["text"],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 100000,
        maxTokens: 4000,
      },
    ],
    streamSimple: (_model: any, _context: any, _options: any) => {
      const stream = createAssistantMessageEventStream();
      const msg = {
        role: "assistant",
        content: [{ type: "text", text: `Mock response at continuations=${continuations}` }],
        api: "mock-api",
        provider: "mock-provider",
        model: "mock-model",
        usage: { input: 10, output: 10, cacheRead: 0, cacheWrite: 0, totalTokens: 20, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
        stopReason: "stop",
        timestamp: Date.now(),
      };
      setTimeout(() => {
        stream.push({ type: "done", reason: "stop", message: msg as any });
        stream.end();
      }, 10);
      return stream;
    },
  });

  pi.on("agent_before_settle", async () => {
    if (continuations < 2) {
      continuations++;
      pi.appendEntry("h2_continuation", { count: continuations });
      return {
        continue: true,
        entries: [
          {
            type: "custom_message",
            customType: "continuation_prompt",
            content: `Continuation #${continuations}`,
            display: true,
          } as any,
        ],
      };
    }
    return { continue: false };
  });
}
