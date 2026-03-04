# CLAUDE.md — alive-memory SDK

## Project

Standalone cognitive memory layer for persistent AI characters. Python 3.12+, SQLite (aiosqlite), three-tier architecture.

Extracted from the Shopkeeper engine into a reusable package.

## Repository Structure

```
alive_memory/       # The SDK package (three-tier: day → hot → cold)
  intake/           # Event → Perception → DayMoment (salience gating)
  recall/           # Keyword grep over hot memory markdown files
  consolidation/    # Sleep pipeline: moments → journal → cold embeddings
  hot/              # Tier 2: MemoryReader/MemoryWriter for markdown files
  identity/         # Self-model, drift detection, evolution
  meta/             # Self-tuning parameter controller
  storage/          # SQLite backend (Tier 1 + Tier 3)
  embeddings/       # Vector providers (hash-based local, OpenAI API)
  llm/              # LLM providers (Anthropic, OpenRouter)
  server/           # Optional REST API (FastAPI)
  adapters/         # Optional LangChain integration
tests/              # Integration tests
benchmarks/         # Comparative benchmark framework (7 systems)
docs/               # Integration guide, architecture plans
pyproject.toml      # Package config (hatchling)
```

## Boundary Rule

`alive_memory/` NEVER imports from application code. It is a standalone library.

## Running Tests

```bash
pytest
```

## Code Style

- Python asyncio throughout
- Type hints on function signatures
- `from __future__ import annotations` in every module
- ruff for linting (config in pyproject.toml)

## Package Build

```bash
pip install -e ".[dev]"     # dev install
pip install build && python -m build  # build wheel
```

## Known Gotchas

- **DriftDetector cooldown initialization**: When implementing cycle-based cooldown, initialize `_last_drift_cycle` to `None` (not `0`), otherwise the first detection at any cycle < cooldown_cycles will be suppressed. Check `is not None` before comparing.
