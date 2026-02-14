/**
 * Standalone Agent Core with hooks and lifecycle management.
 * Built on the OpenRouter SDK with an EventEmitter-based event system.
 */

import { OpenRouter } from "@openrouter/sdk";
import { EventEmitter } from "eventemitter3";
import type { Tool } from "./tools.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AgentConfig {
  /** OpenRouter API key (required). */
  apiKey: string;
  /** Model identifier – defaults to 'openrouter/auto'. */
  model?: string;
  /** System-level instructions for the agent. */
  instructions?: string;
  /** Pre-registered tools. More can be added at runtime with addTool(). */
  tools?: Tool[];
  /** Maximum agentic loop iterations per send() call (default 10). */
  maxSteps?: number;
}

/** Internal tool call shape. */
interface ToolCallInfo {
  id: string;
  type: "function";
  function: { name: string; arguments: string };
}

// SDK-aligned message types (union discriminated by role).
type SystemMsg = { role: "system"; content: string };
type UserMsg = { role: "user"; content: string };
type AssistantMsg = {
  role: "assistant";
  content?: string | null;
  toolCalls?: ToolCallInfo[];
};
type ToolMsg = { role: "tool"; content: string; toolCallId: string };
export type SdkMessage = SystemMsg | UserMsg | AssistantMsg | ToolMsg;

// Events the agent can emit.
export interface AgentEvents {
  "message:user": (content: string) => void;
  "message:assistant": (content: string) => void;
  "stream:delta": (chunk: string) => void;
  "stream:end": (fullText: string) => void;
  "tool:call": (name: string, args: Record<string, unknown>) => void;
  "tool:result": (name: string, result: string) => void;
  "thinking:start": () => void;
  "thinking:end": () => void;
  error: (err: Error) => void;
}

// ---------------------------------------------------------------------------
// Agent
// ---------------------------------------------------------------------------

export class Agent extends EventEmitter<AgentEvents> {
  private client: OpenRouter;
  private model: string;
  private instructions: string;
  private tools: Map<string, Tool> = new Map();
  private messages: SdkMessage[] = [];
  private maxSteps: number;

  constructor(config: AgentConfig) {
    super();

    this.client = new OpenRouter({ apiKey: config.apiKey });
    this.model = config.model ?? "openrouter/auto";
    this.instructions = config.instructions ?? "You are a helpful assistant.";
    this.maxSteps = config.maxSteps ?? 10;

    if (config.tools) {
      for (const tool of config.tools) {
        this.tools.set(tool.name, tool);
      }
    }
  }

  // ---- Public API ---------------------------------------------------------

  /** Update the system instructions at runtime. */
  setInstructions(instructions: string): void {
    this.instructions = instructions;
  }

  /** Register a tool at runtime. */
  addTool(tool: Tool): void {
    this.tools.set(tool.name, tool);
  }

  /** Return a copy of conversation history. */
  getMessages(): SdkMessage[] {
    return [...this.messages];
  }

  /** Clear conversation history. */
  clearHistory(): void {
    this.messages = [];
  }

  /** Send a user message and stream the assistant response. */
  async send(content: string): Promise<string> {
    this.messages.push({ role: "user", content });
    this.emit("message:user", content);

    let fullResponse = "";

    for (let step = 0; step < this.maxSteps; step++) {
      const result = await this.runStep();

      if (result.type === "text") {
        fullResponse = result.content;
        break;
      }

      if (result.type === "tool_calls") {
        for (const tc of result.toolCalls) {
          const toolResult = await this.executeTool(tc);
          this.messages.push({
            role: "tool",
            content: toolResult,
            toolCallId: tc.id,
          });
        }
        continue;
      }
    }

    this.messages.push({ role: "assistant", content: fullResponse });
    this.emit("message:assistant", fullResponse);
    this.emit("stream:end", fullResponse);

    return fullResponse;
  }

  /** Non-streaming convenience wrapper. */
  async sendSync(content: string): Promise<string> {
    return this.send(content);
  }

  // ---- Internals ----------------------------------------------------------

  private buildToolDefs() {
    if (this.tools.size === 0) return undefined;

    return Array.from(this.tools.values()).map((t) => ({
      type: "function" as const,
      function: {
        name: t.name,
        description: t.description,
        parameters: t.parameters as { [k: string]: any },
      },
    }));
  }

  private async runStep(): Promise<
    | { type: "text"; content: string }
    | { type: "tool_calls"; toolCalls: ToolCallInfo[] }
  > {
    this.emit("thinking:start");

    try {
      const allMessages: SdkMessage[] = [
        { role: "system", content: this.instructions },
        ...this.messages,
      ];

      // Use chat.send() with stream: true — returns an async iterable
      // of ChatStreamingResponseChunkData objects.
      const stream = await this.client.chat.send({
        model: this.model,
        messages: allMessages as any,
        tools: this.buildToolDefs(),
        stream: true,
      });

      let accumulated = "";
      const toolCallAccumulators: Map<
        number,
        { id: string; name: string; arguments: string }
      > = new Map();

      for await (const chunk of stream) {
        const choice = chunk.choices?.[0];
        if (!choice) continue;

        const delta = choice.delta;

        // Text content
        if (delta.content) {
          accumulated += delta.content;
          this.emit("stream:delta", delta.content);
        }

        // Tool calls (may arrive across multiple streamed chunks)
        if (delta.toolCalls) {
          for (const tc of delta.toolCalls) {
            const idx = tc.index;
            if (!toolCallAccumulators.has(idx)) {
              toolCallAccumulators.set(idx, {
                id: tc.id ?? "",
                name: tc.function?.name ?? "",
                arguments: "",
              });
            }
            const acc = toolCallAccumulators.get(idx)!;
            if (tc.id) acc.id = tc.id;
            if (tc.function?.name) acc.name = tc.function.name;
            if (tc.function?.arguments)
              acc.arguments += tc.function.arguments;
          }
        }
      }

      this.emit("thinking:end");

      // Build completed tool calls from accumulators.
      const toolCalls: ToolCallInfo[] = [];
      for (const [, acc] of toolCallAccumulators) {
        toolCalls.push({
          id: acc.id,
          type: "function",
          function: { name: acc.name, arguments: acc.arguments },
        });
      }

      if (toolCalls.length > 0) {
        this.messages.push({
          role: "assistant",
          content: accumulated || null,
          toolCalls,
        });
        return { type: "tool_calls", toolCalls };
      }

      return { type: "text", content: accumulated };
    } catch (err) {
      this.emit("thinking:end");
      const error = err instanceof Error ? err : new Error(String(err));
      this.emit("error", error);
      throw error;
    }
  }

  private async executeTool(tc: ToolCallInfo): Promise<string> {
    const tool = this.tools.get(tc.function.name);
    if (!tool) {
      const msg = `Unknown tool: ${tc.function.name}`;
      this.emit("error", new Error(msg));
      return JSON.stringify({ error: msg });
    }

    let args: Record<string, unknown>;
    try {
      args = JSON.parse(tc.function.arguments);
    } catch {
      args = {};
    }

    this.emit("tool:call", tc.function.name, args);

    try {
      const result = await tool.execute(args);
      const resultStr =
        typeof result === "string" ? result : JSON.stringify(result);
      this.emit("tool:result", tc.function.name, resultStr);
      return resultStr;
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      this.emit("error", error);
      return JSON.stringify({ error: error.message });
    }
  }
}
