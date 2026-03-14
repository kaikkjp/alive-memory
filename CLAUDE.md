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
tools/              # Developer tools (not shipped in wheel)
  autotune/         # Config parameter optimizer (mutation + scoring)
  evolve/           # Algorithm optimizer (LLM coding agent + eval suite)
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

- **Evolve overfitting signal is inverted**: In `tools/evolve/types.py`, `overfitting_signal` returns `train.aggregate_score - held_out.aggregate_score`. Since lower scores = better, true overfitting (train much better than held-out) produces a *negative* value, but `should_promote()` checks `> 0.15`. This means the guard catches the wrong case. Tests in `test_evolve.py` are built around the current (wrong) behavior, so fixing requires updating both. Tracked for a separate fix.

- **Trait dedup cooldown is per-consolidation-cycle, not cross-cycle**: The `trait_cache` in `consolidation/__init__.py` is created fresh each `consolidate()` call. This means the 300s cooldown in `fact_extraction._trait_is_duplicate()` only prevents duplicates *within* a single consolidation pass, not across nap→full sleep cycles. The previous module-level `_recent_traits` dict provided cross-cycle protection but leaked state between independent `AliveMemory` instances. If cross-cycle dedup is needed, persist recent trait writes to SQLite with timestamps instead.
