# The Shopkeeper

A persistent AI character engine. She runs a shop, keeps a journal, collects objects, and remembers visitors. She is not a chatbot — she has drives, moods, and an internal life that continues even when no one is visiting.

## Prerequisites

- Python 3.12+
- An [OpenRouter API key](https://openrouter.ai/keys)

## Setup

```bash
# Clone and enter the project
git clone <repo-url> && cd alive

# Install dependencies
pip install -r requirements.txt

# Set your API key
export OPENROUTER_API_KEY='sk-or-v1-...'
```

## Running

### Option A: Standalone (single terminal)

```bash
python terminal.py
```

Starts the heartbeat engine in-process and opens a visitor terminal. Good for quick sessions.

### Option B: Server + Client (persistent)

```bash
# Terminal 1 — start the persistent server
python heartbeat_server.py

# Terminal 2 — connect as a visitor
python terminal.py --connect
```

The server keeps running between visitor sessions. She continues her internal life (journal writing, mood changes, shop rearrangement) while no one is connected.

## Testing

```bash
pip install -r requirements.txt  # includes pytest + pytest-asyncio
python -m pytest tests/ -v
```

## Manual Death-Spiral Harness

Run sequential failure/recovery stress episodes and fit survival models:

```bash
python -m experiments.death_spiral_survival --replicates 120 --out-dir experiments/logs/death_spiral
```

Outputs:
- `collapse_survival.csv` — time-to-collapse rows
- `recovery_survival.csv` — time-to-recovery rows (post-collapse)
- `survival_summary.json` — Cox + AFT-style estimates and group summaries
- `trajectory_samples.json` — sample turn-by-turn traces for inspection

## Project Structure

```
heartbeat_server.py     # TCP + HTTP + WebSocket server
heartbeat.py            # Cognitive cycle engine (perception → routing → LLM → action)
terminal.py             # CLI visitor interface + debug dashboard
sleep.py                # End-of-day reflection + memory consolidation
prompt_assembler.py     # Builds system prompt for cortex
seed.py                 # Initial data for a fresh database

api/
  dashboard_routes.py   # Dashboard HTTP endpoint handlers

db/                     # SQLite persistence (package)
  connection.py         # DB setup, migrations, transactions
  events.py             # Event store, inbox
  state.py              # Room, drives, engagement state
  memory.py             # Visitors, traits, totems, journal, cold search
  content.py            # Threads, content pool, arbiter
  analytics.py          # Cycle log, LLM costs, actions, habits

config/
  identity.py           # Character profile + voice rules

models/
  event.py              # Event dataclass
  pipeline.py           # Typed contracts between pipeline stages
  state.py              # State models (room, drives, visitors, etc.)

pipeline/
  sensorium.py          # Raw events → perceptions
  gates.py              # Perception filtering
  thalamus.py           # Routing decisions (engage / idle / rest)
  cortex.py             # LLM call (Claude Sonnet)
  validator.py          # Response format/schema validation
  basal_ganglia.py      # Multi-intention action selection (Gates 1-6)
  body.py               # Action execution
  output.py             # Post-action processing + metacognitive monitor
  action_registry.py    # Action capabilities, energy costs, cooldowns
  hypothalamus.py       # Drive math (deterministic)
  hippocampus.py        # Memory recall
  hippocampus_write.py  # Memory consolidation
  affect.py             # Emotional lens
  arbiter.py            # Attention allocation across channels
  context_bands.py      # Coarse-grained trigger context for habit matching
  day_memory.py         # Flashbulb moment recording
  sanitize.py           # Input sanitization
  enrich.py             # URL metadata fetching
  ack.py                # Instant acknowledgments

tests/                  # pytest test suite (420+ tests)
```

## Architecture

Single LLM call per cognitive cycle (`pipeline/cortex.py`). Everything else is deterministic — drives math, routing, validation, memory retrieval. The shopkeeper runs on an async heartbeat loop that processes events from an inbox queue.

```
Events → Inbox → Sensorium → Gates → Affect → Hypothalamus → Thalamus
                                                                  │
                                           Hippocampus (recall) ←─┘
                                                  │
                                               Cortex (LLM)
                                                  │
                                              Validator
                                                  │
                                           Basal Ganglia (select)
                                                  │
                                               Body (execute)
                                                  │
                                               Output → Hippocampus Write
```

## Data

Runtime data lives in `data/shopkeeper.db` (SQLite, auto-created on first run). The database is gitignored — each instance starts fresh and develops its own history.
