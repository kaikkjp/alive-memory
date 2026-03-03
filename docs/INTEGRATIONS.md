# Integration Guide

alive-memory can be consumed by any language or framework via its REST API, or directly in Python via the SDK and adapters.

## Table of Contents

- [REST API Server](#rest-api-server)
- [API Reference](#api-reference)
- [LangChain Integration](#langchain-integration)
- [ElizaOS Integration](#elizaos-integration)
- [Generic REST Usage](#generic-rest-usage)

---

## REST API Server

### Installation

```bash
pip install alive-memory[server]
```

### Running

```bash
# Default: http://0.0.0.0:8100
alive-memory-server

# With configuration
ALIVE_PORT=9000 ALIVE_DB=my_agent.db alive-memory-server
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ALIVE_HOST` | `0.0.0.0` | Server bind address |
| `ALIVE_PORT` | `8100` | Server port |
| `ALIVE_DB` | `memory.db` | SQLite database path |
| `ALIVE_CONFIG` | *(none)* | Path to alive config YAML |
| `ALIVE_API_KEY` | *(none)* | Bearer token for authentication |
| `ALIVE_CORS_ORIGINS` | `*` | Comma-separated allowed origins |

### Authentication

If `ALIVE_API_KEY` is set, all endpoints except `/health` require a bearer token:

```bash
curl -H "Authorization: Bearer your-key" http://localhost:8100/state
```

---

## API Reference

### `GET /health`

Health check. Always accessible (no auth required).

```bash
curl http://localhost:8100/health
# {"status":"ok","version":"0.2.0"}
```

### `POST /intake`

Record an event and form a memory.

```bash
curl -X POST http://localhost:8100/intake \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "conversation",
    "content": "The user asked about Tokyo weather",
    "metadata": {"user_id": "u123"}
  }'
```

**Request body:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `event_type` | string | yes | `conversation`, `action`, `observation`, `system` |
| `content` | string | yes | Event content text |
| `metadata` | object | no | Additional metadata |
| `timestamp` | string | no | ISO 8601 datetime (defaults to now) |

**Response:** `MemoryResponse`

### `POST /recall`

Retrieve memories relevant to a query.

```bash
curl -X POST http://localhost:8100/recall \
  -H "Content-Type: application/json" \
  -d '{"query": "Tokyo weather", "limit": 3}'
```

**Request body:**
| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | string | yes | | Search query text |
| `limit` | int | no | 5 | Max results (1-100) |
| `min_strength` | float | no | 0.0 | Filter by minimum strength |

**Response:** `MemoryResponse[]`

### `POST /consolidate`

Run memory consolidation (sleep cycle).

```bash
curl -X POST http://localhost:8100/consolidate \
  -H "Content-Type: application/json" \
  -d '{"depth": "nap"}'
```

**Request body:**
| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `whispers` | object[] | no | | Config changes to process |
| `depth` | string | no | `full` | `full` or `nap` |

**Response:** `ConsolidationReportResponse`

### `GET /state`

Get the current cognitive state (mood, drives, energy).

```bash
curl http://localhost:8100/state
```

**Response:** `CognitiveStateResponse`

### `GET /identity`

Get the current self-model (traits, behavioral summary).

```bash
curl http://localhost:8100/identity
```

**Response:** `SelfModelResponse`

### `POST /drives/{name}`

Manually adjust a drive value.

```bash
curl -X POST http://localhost:8100/drives/curiosity \
  -H "Content-Type: application/json" \
  -d '{"delta": 0.1}'
```

**Request body:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `delta` | float | yes | Change amount (-1.0 to 1.0) |

**Response:** `DriveStateResponse`

### `POST /backstory`

Inject a backstory memory (high-strength semantic memory).

```bash
curl -X POST http://localhost:8100/backstory \
  -H "Content-Type: application/json" \
  -d '{
    "content": "I was created in a digital garden to help humans understand AI.",
    "title": "origin"
  }'
```

**Request body:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `content` | string | yes | Backstory content |
| `title` | string | no | Optional title |

**Response:** `MemoryResponse`

---

## LangChain Integration

### Installation

```bash
pip install alive-memory[langchain]
```

### Chat Message History

Use `AliveMessageHistory` as a drop-in replacement for LangChain's chat history backends. Messages are stored as memories with emotional valence and cognitive metadata.

```python
from alive_memory import AliveMemory
from alive_memory.adapters.langchain import AliveMessageHistory
from langchain_core.messages import HumanMessage, AIMessage

# Initialize
memory = AliveMemory(storage="agent.db")
await memory.initialize()

history = AliveMessageHistory(memory=memory)

# Add messages (stored via intake)
await history.aadd_messages([
    HumanMessage(content="What's the weather in Tokyo?"),
    AIMessage(content="It's sunny and 22°C in Tokyo today."),
])

# Retrieve messages (recalled with cognitive ranking)
messages = await history.aget_messages()
```

### RAG Retriever

Use `AliveRetriever` in LangChain RAG chains. Memories are recalled using keyword grep over hot memory files with cognitive re-ranking (mood congruence, drive coupling).

```python
from alive_memory import AliveMemory
from alive_memory.adapters.langchain import AliveRetriever
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough

memory = AliveMemory(storage="agent.db")
await memory.initialize()

retriever = AliveRetriever(memory=memory, recall_limit=5)

# Use in a chain
prompt = ChatPromptTemplate.from_template(
    "Context: {context}\n\nQuestion: {question}"
)

chain = (
    {"context": retriever, "question": RunnablePassthrough()}
    | prompt
    | llm
)

result = await chain.ainvoke("What do you remember about Tokyo?")
```

---

## ElizaOS Integration

The Eliza plugin connects ElizaOS agents to alive-memory via the REST API.

### Setup

1. Start the alive-memory server:
```bash
ALIVE_API_KEY=your-secret alive-memory-server
```

2. Install the plugin in your ElizaOS project:
```bash
cd alive_memory/eliza
npm install
npm run build
```

3. Configure your ElizaOS agent settings:
```
ALIVE_MEMORY_URL=http://localhost:8100
ALIVE_MEMORY_API_KEY=your-secret
```

### Features

**REMEMBER action** — Stores conversation messages as long-term memories:
```
User: "My favorite color is blue."
Agent: "I'll remember that!" [action: REMEMBER]
```

**Context provider** — Automatically recalls relevant memories and injects them into the agent's prompt context. When a user sends a message, the plugin recalls related memories and adds them as context.

### Using the Client Directly

```typescript
import { AliveMemoryClient } from "@alive-memory/eliza-plugin";

const client = new AliveMemoryClient({
  baseUrl: "http://localhost:8100",
  apiKey: "your-secret",
});

// Store a memory
await client.intake({
  event_type: "conversation",
  content: "User prefers dark mode",
});

// Recall memories
const memories = await client.recall({ query: "user preferences", limit: 5 });

// Check cognitive state
const state = await client.getState();
console.log(`Mood: ${state.mood.word}, Energy: ${state.energy}`);
```

---

## Generic REST Usage

Any language or framework can use alive-memory through its REST API. Here are examples in common languages:

### JavaScript/TypeScript (fetch)

```javascript
const BASE = "http://localhost:8100";

// Store a memory
const mem = await fetch(`${BASE}/intake`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    event_type: "conversation",
    content: "User mentioned they like hiking",
  }),
}).then((r) => r.json());

// Recall
const memories = await fetch(`${BASE}/recall`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ query: "user hobbies", limit: 5 }),
}).then((r) => r.json());
```

### Ruby

```ruby
require "net/http"
require "json"

uri = URI("http://localhost:8100/intake")
http = Net::HTTP.new(uri.host, uri.port)

req = Net::HTTP::Post.new(uri, "Content-Type" => "application/json")
req.body = { event_type: "conversation", content: "Hello from Ruby" }.to_json

res = http.request(req)
puts JSON.parse(res.body)
```

### Go

```go
body := `{"event_type":"conversation","content":"Hello from Go"}`
resp, err := http.Post("http://localhost:8100/intake", "application/json", strings.NewReader(body))
```
