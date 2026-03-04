# @alive-memory/eliza-plugin

ElizaOS plugin for alive-memory cognitive memory layer.

## Setup

1. Start the alive-memory server:
```bash
pip install alive-memory[server]
ALIVE_API_KEY=your-secret alive-memory-server
```

2. Build the plugin:
```bash
cd alive_memory/eliza
npm install
npm run build
```

3. Configure your ElizaOS agent:
```
ALIVE_MEMORY_URL=http://localhost:8100
ALIVE_MEMORY_API_KEY=your-secret
```

## Features

- **REMEMBER action** — stores conversation messages as day moments via `/intake`
- **Context provider** — recalls relevant memories via `/recall` and injects them into the agent prompt

## Using the Client Directly

```typescript
import { AliveMemoryClient } from "@alive-memory/eliza-plugin";

const client = new AliveMemoryClient({
  baseUrl: "http://localhost:8100",
  apiKey: "your-secret",
});

// Store a memory (returns DayMomentResponse or null)
const moment = await client.intake({
  event_type: "conversation",
  content: "User prefers dark mode",
});

// Recall from hot memory (returns RecallContextResponse)
const ctx = await client.recall({ query: "user preferences", limit: 5 });
console.log(ctx.journal_entries);
console.log(ctx.visitor_notes);

// Check cognitive state
const state = await client.getState();
console.log(`Mood: ${state.mood.word}, Energy: ${state.energy}`);
```
