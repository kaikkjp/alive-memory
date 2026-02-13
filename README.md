# The Shopkeeper

A persistent AI character engine. She runs a shop, keeps a journal, collects objects, and remembers visitors. She is not a chatbot — she has drives, moods, and an internal life that continues even when no one is visiting.

## Prerequisites

- Python 3.12+
- An [Anthropic API key](https://console.anthropic.com/)

## Setup

```bash
# Clone and enter the project
git clone <repo-url> && cd alive

# Install dependencies
pip install -r requirements.txt

# Set your API key
export ANTHROPIC_API_KEY='sk-ant-...'
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

## Project Structure

```
heartbeat_server.py     # TCP server — persistent background process
heartbeat.py            # Cognitive cycle engine (perception → routing → LLM → action)
terminal.py             # CLI visitor interface + debug dashboard
db.py                   # SQLite persistence layer
seed.py                 # Initial data for a fresh database

config/
  identity.py           # Character profile + voice rules

models/
  event.py              # Event dataclass
  state.py              # State models (room, drives, visitors, etc.)

pipeline/
  sensorium.py          # Raw events → perceptions
  gates.py              # Perception filtering
  thalamus.py           # Routing decisions (engage / idle / rest)
  cortex.py             # LLM call (Claude Sonnet)
  validator.py          # Response validation + canonical trait checks
  executor.py           # Action execution
  hypothalamus.py       # Drive math (deterministic)
  hippocampus.py        # Memory recall
  hippocampus_write.py  # Memory consolidation
  affect.py             # Emotional lens
  sanitize.py           # Input sanitization
  enrich.py             # URL metadata fetching
  ack.py                # Instant acknowledgments

tests/                  # pytest test suite
```

## Architecture

Single LLM call per cognitive cycle (`pipeline/cortex.py`). Everything else is deterministic — drives math, routing, validation, memory retrieval. The shopkeeper runs on an async heartbeat loop that processes events from an inbox queue.

```
Events → Inbox → Sensorium → Gates → Thalamus → Cortex → Validator → Executor
                                                             ↑
                                              Hippocampus (memory recall)
                                              Hypothalamus (drive state)
                                              Affect (emotional lens)
```

## Data

Runtime data lives in `data/shopkeeper.db` (SQLite, auto-created on first run). The database is gitignored — each instance starts fresh and develops its own history.
