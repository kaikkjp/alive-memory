# Code Assistant Agent (OpenRouter)

A modular AI code assistant built on the [OpenRouter SDK](https://openrouter.ai/docs/quickstart). Uses streaming responses, tool calling, and an event-driven architecture.

## Quick Start

```bash
# 1. Install dependencies
npm install

# 2. Set your API key
export OPENROUTER_API_KEY=sk-or-v1-your-key-here

# 3. Build & run
npm run dev
```

## Usage

```bash
# Default model (Claude Sonnet 4)
npm start

# Choose a different model
node dist/cli.js --model=google/gemini-2.5-pro

# Any model on OpenRouter
node dist/cli.js --model=openrouter/auto
```

### In-chat commands

| Command    | Description               |
|------------|---------------------------|
| `/clear`   | Clear conversation history |
| `/history` | Show message history       |
| `exit`     | Quit the agent             |

## Available Tools

| Tool           | Description                                    |
|----------------|------------------------------------------------|
| `read_file`    | Read file contents                             |
| `write_file`   | Create or overwrite files                      |
| `list_files`   | List directory contents                        |
| `run_command`  | Execute shell commands (tests, git, etc.)      |
| `search_files` | Grep for patterns across a codebase            |

## Architecture

```
src/
├── agent.ts    → EventEmitter-based agent core with streaming + tool loop
├── tools.ts    → Tool definitions (filesystem, shell, search)
└── cli.ts      → Interactive REPL entry point
```

The agent core is **interface-agnostic** — you can swap the CLI for an HTTP server, Discord bot, or any other interface by listening to the same events.

## Adding Custom Tools

```typescript
import { Agent } from "./agent.js";
import type { Tool } from "./tools.js";

const myTool: Tool = {
  name: "my_tool",
  description: "Does something useful",
  parameters: {
    type: "object",
    properties: {
      input: { type: "string", description: "The input" },
    },
    required: ["input"],
  },
  async execute(args) {
    return `Result for ${args.input}`;
  },
};

agent.addTool(myTool);
```
