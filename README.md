# alive-memory

Autobiographical, identity-preserving, emotionally weighted memory for
persistent AI agents. Three-tier architecture: salience-gated intake,
keyword-based recall, and LLM-powered consolidation with identity tracking.

> **Alpha release.** API may change. [Feedback welcome.](https://github.com/TriMinhPham/alive-memory/issues)

```bash
pip install alive-memory
```

## Quick start

```python
import asyncio
from alive_memory import AliveMemory

async def main():
    async with AliveMemory(storage="agent.db", memory_dir="agent-memory") as memory:
        # Record events (only salient ones become memories)
        await memory.intake("conversation", "User asked about Python decorators")
        await memory.intake("conversation", "User mentioned they're building a CLI tool")

        # Recall relevant context
        context = await memory.recall("decorators")
        print(context.to_prompt())  # formatted text ready for LLM injection

        # Consolidate (run periodically — processes memories, writes reflections)
        report = await memory.consolidate()
        print(f"Processed {report.moments_processed} moments")

asyncio.run(main())
```

No async? Use sync wrappers:

```python
from alive_memory import AliveMemory

memory = AliveMemory(storage="agent.db", memory_dir="agent-memory")
memory.intake_sync("conversation", "User said hello")
context = memory.recall_sync("hello")
print(context.to_prompt())
```

## Integration example

```python
from alive_memory import AliveMemory

async def agent_loop(memory: AliveMemory):
    conversation_count = 0

    while True:
        user_input = input("> ")

        # Record the conversation
        await memory.intake("conversation", f"User: {user_input}")

        # Recall relevant context for the LLM
        context = await memory.recall(user_input)

        # Build your LLM prompt with memory context
        system_prompt = f"You are a helpful assistant.\n\n{context.to_prompt()}"

        # ... call your LLM with system_prompt + user_input ...

        conversation_count += 1
        if conversation_count % 10 == 0:
            await memory.consolidate(depth="nap")  # light consolidation
```

## API reference

### `AliveMemory(storage, *, memory_dir, llm, config)`

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `storage` | `str` or `BaseStorage` | `"memory.db"` | SQLite path or storage backend |
| `memory_dir` | `str` or `Path` | temp dir | Directory for hot memory files |
| `llm` | `str`, callable, or `LLMProvider` | `None` | LLM for consolidation |
| `config` | `dict` or `AliveConfig` | defaults | Configuration overrides |

For an always-on agent, pass a durable `memory_dir`. If omitted, hot memory
uses a temporary directory; the SQLite DB survives, but journal files,
visitor notes, reflections, and self-knowledge can disappear after restart.

LLM options: `"anthropic"`, `"openai"`, `"openrouter"`, `"gemini"`, or any `async def(prompt, system="") -> str`.

### Core methods

| Method | Async | Sync | Returns | Description |
|--------|-------|------|---------|-------------|
| `intake(event_type, content)` | `await` | `intake_sync()` | `DayMoment \| None` | Record an event (salience-gated) |
| `recall(query)` | `await` | `recall_sync()` | `RecallContext` | Retrieve relevant memories |
| `consolidate(depth="full")` | `await` | `consolidate_sync()` | `SleepReport` | Process memories (sleep) |
| `sleep()` | `await` | `sleep_sync()` | `SleepCycleReport` | Full sleep cycle with identity |
| `get_state()` | `await` | — | `CognitiveState` | Current mood, drives, energy |
| `get_identity()` | `await` | — | `SelfModel` | Persistent self-model |

### `RecallContext`

```python
context = await memory.recall("query")

# Structured access
context.episodic       # events and conversations
context.observations   # notes about the user
context.semantic       # general knowledge
context.reflections    # past reflections
context.thread         # conversation context
context.entities       # structured objects
context.traits         # user attributes

# Formatted for LLM
context.to_prompt()    # → "## Relevant Context\n\n### Recent Events\n- ..."
```

### When to consolidate

- **`consolidate(depth="nap")`** — light, every ~10 conversations. No cold search or dreams.
- **`consolidate(depth="full")`** — complete pipeline. Reflection, dreaming, cold embedding. Run daily or on shutdown.
- **`sleep()`** — full orchestrated cycle including identity evolution and meta-tuning.

## Extras

```bash
pip install alive-memory[anthropic]   # Claude LLM provider
pip install alive-memory[openai]      # OpenAI LLM provider
pip install alive-memory[openrouter]  # OpenRouter LLM provider
pip install alive-memory[all]         # Everything
```

## How it works

| Tier | Name | Storage | When | Purpose |
|------|------|---------|------|---------|
| 1 | Day Memory | SQLite | `intake()` | Ephemeral salient moments |
| 2 | Hot Memory | Markdown files | `recall()` | Searchable text (journal, reflections) |
| 3 | Cold Memory | SQLite vectors | `consolidate()` | Long-term vector archive |

Events pass through a perception pipeline with salience gating — not everything becomes a memory. Consolidation ("sleep") processes day memories through LLM reflection, writes to the hot memory journal, and embeds to the cold archive. An identity system tracks behavioral drift over time.

For consistent identity and tastes, callers should pass stable metadata on
conversation events, especially `visitor_id`, `session_id`, `turn_index`,
`role`, and timestamps. Structured preference and trait extraction depend on
that identity context.

## Development

```bash
git clone https://github.com/TriMinhPham/alive-memory.git
cd alive-memory
pip install -e ".[dev]"
pytest
```

## License

MIT
