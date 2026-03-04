/**
 * ElizaOS plugin for alive-memory integration.
 *
 * Provides:
 * - REMEMBER action: stores conversation messages as memories
 * - alive-memory provider: injects recalled context into agent prompts
 */

import { AliveMemoryClient, type AliveClientConfig } from "./client";
import type { RecallContextResponse } from "./types";

export { AliveMemoryClient } from "./client";
export type { AliveClientConfig } from "./client";
export * from "./types";

// ── ElizaOS Plugin Types ──────────────────────────────────────────
// Minimal type definitions for ElizaOS plugin interface.
// In a real project, import from @elizaos/core.

interface IAgentRuntime {
  getSetting(key: string): string | undefined;
}

interface Memory {
  content: { text: string };
  userId: string;
  roomId: string;
}

interface State {
  [key: string]: unknown;
}

interface Action {
  name: string;
  description: string;
  similes: string[];
  validate: (
    runtime: IAgentRuntime,
    message: Memory,
  ) => Promise<boolean>;
  handler: (
    runtime: IAgentRuntime,
    message: Memory,
    state?: State,
  ) => Promise<void>;
  examples: Array<Array<{ user: string; content: { text: string; action?: string } }>>;
}

interface Provider {
  get: (
    runtime: IAgentRuntime,
    message: Memory,
    state?: State,
  ) => Promise<string>;
}

interface Plugin {
  name: string;
  description: string;
  actions: Action[];
  providers: Provider[];
}

// ── Helpers ──────────────────────────────────────────────────────

function getClient(runtime: IAgentRuntime): AliveMemoryClient {
  const baseUrl =
    runtime.getSetting("ALIVE_MEMORY_URL") || "http://localhost:8100";
  const apiKey = runtime.getSetting("ALIVE_MEMORY_API_KEY");
  return new AliveMemoryClient({ baseUrl, apiKey });
}

function formatRecallContext(ctx: RecallContextResponse): string {
  const sections: string[] = [];

  if (ctx.journal_entries.length > 0) {
    sections.push(`Journal:\n${ctx.journal_entries.join("\n")}`);
  }
  if (ctx.visitor_notes.length > 0) {
    sections.push(`Visitor notes:\n${ctx.visitor_notes.join("\n")}`);
  }
  if (ctx.self_knowledge.length > 0) {
    sections.push(`Self-knowledge:\n${ctx.self_knowledge.join("\n")}`);
  }
  if (ctx.reflections.length > 0) {
    sections.push(`Reflections:\n${ctx.reflections.join("\n")}`);
  }

  if (sections.length === 0) return "";
  return `Recalled memories (${ctx.total_hits} hits):\n${sections.join("\n\n")}`;
}

// ── REMEMBER Action ─────────────────────────────────────────────

const rememberAction: Action = {
  name: "REMEMBER",
  description:
    "Store the current message as a memory in alive-memory for long-term cognitive recall.",
  similes: ["MEMORIZE", "STORE_MEMORY", "SAVE_MEMORY"],

  validate: async (runtime: IAgentRuntime, _message: Memory) => {
    const url = runtime.getSetting("ALIVE_MEMORY_URL");
    return !!url;
  },

  handler: async (
    runtime: IAgentRuntime,
    message: Memory,
    _state?: State,
  ) => {
    const client = getClient(runtime);
    await client.intake({
      event_type: "conversation",
      content: message.content.text,
      metadata: {
        userId: message.userId,
        roomId: message.roomId,
      },
    });
  },

  examples: [
    [
      {
        user: "{{user1}}",
        content: { text: "My favorite color is blue." },
      },
      {
        user: "{{agent}}",
        content: {
          text: "I'll remember that your favorite color is blue!",
          action: "REMEMBER",
        },
      },
    ],
    [
      {
        user: "{{user1}}",
        content: { text: "I'm allergic to peanuts, please remember that." },
      },
      {
        user: "{{agent}}",
        content: {
          text: "Noted — I've stored that important detail.",
          action: "REMEMBER",
        },
      },
    ],
  ],
};

// ── Context Provider ────────────────────────────────────────────

const memoryProvider: Provider = {
  get: async (
    runtime: IAgentRuntime,
    message: Memory,
    _state?: State,
  ): Promise<string> => {
    const url = runtime.getSetting("ALIVE_MEMORY_URL");
    if (!url) return "";

    try {
      const client = getClient(runtime);
      const ctx = await client.recall({
        query: message.content.text,
        limit: 5,
      });
      return formatRecallContext(ctx);
    } catch {
      return "";
    }
  },
};

// ── Plugin ───────────────────────────────────────────────────────

export const aliveMemoryPlugin: Plugin = {
  name: "alive-memory",
  description:
    "Cognitive memory layer — stores and recalls memories with emotional valence, drive coupling, and consolidation.",
  actions: [rememberAction],
  providers: [memoryProvider],
};

export default aliveMemoryPlugin;
