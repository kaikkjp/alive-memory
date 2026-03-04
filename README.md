# alive-memory

Cognitive memory layer for persistent AI characters. Three-tier architecture with salience-gated intake, markdown-based hot recall, and vector-embedded cold archive.

**Status:** v0.3.0 (alpha)

## Quick start

```bash
# Clone
git clone git@github.com:TriMinhPham/Alive-sdk.git
cd Alive-sdk

# Set up Python environment
python3 -m venv .venv
source .venv/bin/activate

# Install in dev mode with all extras
pip install -e ".[all,dev]"

# Run tests
pytest
```

## Usage

```python
from alive_memory import AliveMemory

async with AliveMemory(
    storage="my_agent.db",
    memory_dir="/data/agent/memory",
) as memory:

    # Record an event (returns DayMoment if salient enough, None otherwise)
    moment = await memory.intake("conversation", "User said: Hello!")

    # Recall from hot memory (keyword grep over markdown files)
    context = await memory.recall("greetings", limit=5)
    print(context.journal_entries)
    print(context.visitor_notes)
    print(context.self_knowledge)

    # Check cognitive state
    state = await memory.get_state()
    print(state.mood.word, state.drives.curiosity)

    # Consolidate (sleep) — processes day moments, writes journal, embeds to cold
    report = await memory.consolidate()
    print(f"Processed {report.moments_processed} moments")

    # Full sleep cycle (with optional providers)
    from alive_memory import SleepConfig
    cycle_report = await memory.sleep()
    print(f"Consolidated {cycle_report.moments_consolidated} moments, {cycle_report.dreams_generated} dreams")
```

## Three-tier architecture

| Tier | Name | Storage | Accessed during | Purpose |
|------|------|---------|-----------------|---------|
| 1 | Day Memory | SQLite `day_memory` table | `intake()` | Ephemeral salient moments, salience-gated |
| 2 | Hot Memory | Markdown files on disk | `recall()` | Journal, visitors, reflections, self-knowledge |
| 3 | Cold Memory | SQLite `cold_embeddings` table | `consolidate()` only | Vector archive for historical echoes |

```
alive_memory/
├── types.py              # Core type system (DayMoment, RecallContext, SleepReport, etc.)
├── config.py             # YAML/dict config loader
├── sleep.py              # Sleep cycle orchestrator (sleep_cycle, nap)
├── intake/               # Event → Perception → DayMoment (salience gating)
│   ├── thalamus.py       #   Event → Perception (salience scoring)
│   ├── affect.py         #   Emotional valence computation
│   ├── formation.py      #   Perception → DayMoment (gating + dedup)
│   └── drives.py         #   Drive & mood state updates
├── recall/               # Query → Hot memory grep → RecallContext
│   ├── hippocampus.py    #   Keyword grep over markdown files
│   ├── weighting.py      #   Scoring math (strength, valence, decay)
│   └── context.py        #   Mood-congruent, drive-coupled recall
├── consolidation/        # Sleep pipeline: moments → journal → cold embeddings
│   ├── cold_search.py    #   Find "cold echoes" from old memories
│   ├── dreaming.py       #   LLM-powered dream generation
│   ├── reflection.py     #   LLM-powered per-moment & daily reflection
│   ├── memory_updates.py #   Apply reflection outputs to hot memory
│   └── whisper.py        #   Config changes → dream perceptions
├── hot/                  # Tier 2: Markdown files on disk
│   ├── reader.py         #   MemoryReader: grep-based keyword search
│   └── writer.py         #   MemoryWriter: append-only markdown writes
├── identity/             # Persistent self-model
│   ├── self_model.py     #   Self-representation & trait tracking
│   ├── drift.py          #   Behavioral drift detection
│   ├── evolution.py      #   Identity change resolution
│   └── history.py        #   Developmental snapshots & timelines
├── meta/                 # Self-tuning
│   ├── controller.py     #   Parameter adjustments via feedback loops
│   └── evaluation.py     #   Closed-loop eval & side-effect detection
├── storage/              # Persistence backends (Tier 1 & 3)
│   ├── base.py           #   BaseStorage ABC
│   └── sqlite.py         #   SQLite + aiosqlite
├── embeddings/           # Vector embedding providers
│   ├── base.py           #   EmbeddingProvider protocol
│   ├── local.py          #   Hash-based (deterministic, no API key needed)
│   └── api.py            #   OpenAI API embeddings
├── llm/                  # LLM providers (for consolidation)
│   ├── provider.py       #   LLMProvider protocol
│   ├── anthropic.py      #   Claude via Anthropic API
│   └── openrouter.py     #   OpenRouter gateway
├── server/               # REST API (optional)
│   ├── app.py            #   FastAPI application
│   ├── config.py         #   Server config from env vars
│   ├── models.py         #   Pydantic request/response models
│   └── routes.py         #   Endpoint handlers
└── adapters/             # Framework integrations (optional)
    └── langchain.py      #   AliveMessageHistory + AliveRetriever
```

## Key concepts

- **Intake**: Raw events pass through a perception pipeline (thalamus → affect → drives) and are salience-gated. Only moments that cross a dynamic threshold become DayMoments in Tier 1. Not every event becomes a memory.
- **Recall**: Keyword grep over Tier 2 markdown files (journal, visitors, reflections, self-knowledge). Results are re-ranked by mood congruence and drive coupling. Returns a `RecallContext` with categorized results, not a flat list. Vector search is NOT used during recall.
- **Consolidation**: Periodic "sleep" that processes day moments through context gathering, cold echo search, LLM reflection, journal writing, and vector embedding. Supports `"full"` (complete pipeline) and `"nap"` (light, no cold search or dreams) modes.
- **Identity**: A persistent self-model with trait tracking, behavioral drift detection, and three-tier change resolution (accept/correct/defer).
- **Meta**: Self-tuning parameters that adjust cognitive behavior based on closed-loop evaluation with adaptive cooldowns.
- **Sleep Cycle**: Full orchestrated sleep with whisper → consolidation → meta-review → meta-controller → identity evolution → wake. Each phase is fault-tolerant. Lightweight `nap()` variant for mid-cycle consolidation.

## Extras

```bash
pip install alive-memory[server]      # REST API (FastAPI + uvicorn)
pip install alive-memory[anthropic]   # Claude LLM provider
pip install alive-memory[openrouter]  # OpenRouter LLM provider
pip install alive-memory[embeddings]  # OpenAI embedding provider
pip install alive-memory[langchain]   # LangChain adapters
pip install alive-memory[all]         # Everything
```

See [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) for REST API reference, LangChain usage, and ElizaOS integration.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

## License

MIT
