#!/usr/bin/env node
/**
 * CLI entry point for the code assistant agent.
 *
 * Usage:
 *   OPENROUTER_API_KEY=sk-or-... node dist/cli.js
 *   OPENROUTER_API_KEY=sk-or-... node dist/cli.js --model anthropic/claude-sonnet-4
 */

import { createInterface } from "node:readline";
import { Agent } from "./agent.js";
import { defaultTools } from "./tools.js";

// ---------------------------------------------------------------------------
// Config from env / CLI args
// ---------------------------------------------------------------------------

const apiKey = process.env.OPENROUTER_API_KEY;
if (!apiKey) {
  console.error(
    "Error: OPENROUTER_API_KEY environment variable is required.\n" +
      "Get one at https://openrouter.ai/settings/keys"
  );
  process.exit(1);
}

const modelArg = process.argv.find((a) => a.startsWith("--model="));
const model = modelArg?.split("=")[1] ?? "anthropic/claude-sonnet-4";

// ---------------------------------------------------------------------------
// Create the agent
// ---------------------------------------------------------------------------

const agent = new Agent({
  apiKey,
  model,
  instructions: `You are an expert code assistant. You help developers by:
- Reading, writing, and editing code files
- Running shell commands (tests, linters, builds)
- Searching codebases for patterns and definitions
- Explaining code, debugging, and suggesting improvements

Always use the available tools to interact with the filesystem and run commands.
When asked to make changes, read the relevant files first, then make targeted edits.
Be concise in explanations but thorough in code.`,
  tools: defaultTools,
  maxSteps: 10,
});

// ---------------------------------------------------------------------------
// Wire up event hooks for CLI output
// ---------------------------------------------------------------------------

agent.on("stream:delta", (chunk) => {
  process.stdout.write(chunk);
});

agent.on("stream:end", () => {
  process.stdout.write("\n");
});

agent.on("tool:call", (name, args) => {
  const preview =
    JSON.stringify(args).length > 120
      ? JSON.stringify(args).slice(0, 120) + "..."
      : JSON.stringify(args);
  console.log(`\n🔧 ${name}(${preview})`);
});

agent.on("tool:result", (name, result) => {
  const preview = result.length > 200 ? result.slice(0, 200) + "..." : result;
  console.log(`   ↳ ${preview}\n`);
});

agent.on("error", (err) => {
  console.error(`\n❌ Error: ${err.message}\n`);
});

// ---------------------------------------------------------------------------
// Interactive REPL
// ---------------------------------------------------------------------------

const rl = createInterface({
  input: process.stdin,
  output: process.stdout,
  prompt: "\n🤖 > ",
});

console.log(`
╔══════════════════════════════════════════════════╗
║       Code Assistant Agent (OpenRouter)          ║
║                                                  ║
║  Model: ${model.padEnd(40)}║
║  Tools: ${defaultTools.map((t) => t.name).join(", ").padEnd(40)}║
║                                                  ║
║  Type your request, or 'exit' to quit.           ║
╚══════════════════════════════════════════════════╝
`);

rl.prompt();

rl.on("line", async (line) => {
  const input = line.trim();

  if (!input) {
    rl.prompt();
    return;
  }

  if (input.toLowerCase() === "exit" || input.toLowerCase() === "quit") {
    console.log("Goodbye!");
    process.exit(0);
  }

  if (input.toLowerCase() === "/clear") {
    agent.clearHistory();
    console.log("Conversation cleared.");
    rl.prompt();
    return;
  }

  if (input.toLowerCase() === "/history") {
    const msgs = agent.getMessages();
    console.log(`\n--- ${msgs.length} messages ---`);
    for (const m of msgs) {
      const text = ("content" in m ? String(m.content ?? "") : "");
      const preview = text.length > 100 ? text.slice(0, 100) + "..." : text;
      console.log(`[${m.role}] ${preview}`);
    }
    rl.prompt();
    return;
  }

  try {
    await agent.send(input);
  } catch (err: any) {
    console.error(`Fatal error: ${err.message}`);
  }

  rl.prompt();
});

rl.on("close", () => {
  console.log("\nGoodbye!");
  process.exit(0);
});
