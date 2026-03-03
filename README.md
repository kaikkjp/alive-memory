# alive-memory

Cognitive memory layer for persistent AI characters. Handles memory formation, emotional weighting, drive dynamics, recall ranking, consolidation (sleep), identity persistence, and drift detection.

**Status:** Early development (v0.1.0)

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
make test
```

## Usage

```python
from alive_memory import AliveMemory

memory = AliveMemory(storage="sqlite:///my_character.db")
await memory.initialize()

# Record an event
await memory.intake("conversation", "User said: Hello!")

# Recall memories
results = await memory.recall("greetings", limit=5)

# Check cognitive state
state = await memory.state
print(state.mood.word, state.drives.curiosity)

# Consolidate (sleep)
report = await memory.consolidate()
```

## Architecture

```
alive_memory/
├── types.py              # Core type system (Memory, Perception, DriveState, etc.)
├── config.py             # YAML/dict config loader
├── intake/               # Raw events → perceptions → memories
│   ├── thalamus.py       #   Event → Perception (salience scoring)
│   ├── affect.py         #   Emotional valence computation
│   ├── formation.py      #   Perception → Memory formation
│   └── drives.py         #   Drive state updates
├── recall/               # Memory retrieval
│   ├── hippocampus.py    #   Vector search + re-ranking
│   ├── weighting.py      #   Scoring math (strength, valence, decay)
│   └── context.py        #   Mood-congruent, drive-coupled recall
├── consolidation/        # Sleep cycle
│   ├── strengthening.py  #   Rehearsal → strengthen
│   ├── decay.py          #   Time-based decay
│   ├── pruning.py        #   Remove weak memories
│   ├── merging.py        #   Combine similar memories
│   ├── dreaming.py       #   LLM-powered dream generation
│   ├── reflection.py     #   LLM-powered self-reflection
│   └── whisper.py        #   Config changes → dream perceptions
├── identity/             # Persistent self-model
│   ├── self_model.py     #   Self-representation
│   ├── drift.py          #   Behavioral drift detection
│   ├── evolution.py      #   Identity change resolution
│   └── history.py        #   Developmental snapshots
├── meta/                 # Self-tuning
│   ├── controller.py     #   Parameter adjustments
│   └── evaluation.py     #   Closed-loop eval
├── storage/              # Persistence backends
│   ├── base.py           #   BaseStorage ABC
│   └── sqlite.py         #   SQLite + sqlite-vec
├── embeddings/           # Vector embedding providers
│   ├── local.py          #   Local model
│   └── api.py            #   API-based (OpenAI, etc.)
└── llm/                  # LLM providers (for dreaming/reflection)
    ├── provider.py       #   LLMProvider protocol
    ├── anthropic.py      #   Claude
    └── openrouter.py     #   OpenRouter
```

## Key concepts

- **Intake**: Raw events are converted to structured perceptions, scored for salience, tagged with emotional valence, and formed into memories with drive-coupling metadata.
- **Recall**: Vector similarity search re-ranked by consolidation strength, mood congruence, drive coupling, and recency.
- **Consolidation**: Periodic "sleep" that strengthens important memories, decays weak ones, prunes noise, merges duplicates, and (with an LLM) generates dreams and self-reflections.
- **Identity**: A persistent self-model that evolves over time with drift detection and three-tier change resolution (accept/correct/defer).
- **Meta**: Self-tuning parameters that adjust cognitive behavior based on closed-loop evaluation.

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
