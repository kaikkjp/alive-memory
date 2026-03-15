# Changelog

## 1.0.0a1 (2026-03-15)

First public alpha release on PyPI.

### Added
- Generic public API: `RecallContext` fields renamed (episodic, observations, semantic, thread, entities, traits)
- `to_prompt()` convenience method for LLM prompt injection
- OpenAI LLM provider
- Callable LLM support (pass any async/sync function)
- Sync wrappers: `intake_sync()`, `recall_sync()`, `consolidate_sync()`, `sleep_sync()`

### Changed
- Split autotune/evolve into `tools/` (not shipped in wheel)
- Version: 1.0.0a1

## 0.3.0 (2026-03-04)

Full sleep cycle orchestration, meta-cognition enhancements, and identity evolution.

### Added
- **Sleep orchestrator** (`sleep.py`): `sleep_cycle()` chains whisper → consolidation → meta-review → meta-controller → identity evolution → wake with per-phase fault tolerance
- **Nap variant**: `nap()` convenience function for lightweight mid-cycle consolidation
- **SleepConfig**: dataclass to enable/disable individual sleep phases
- **SleepCycleReport**: comprehensive report with per-phase results and error collection
- **AliveMemory.sleep()**: convenience method on the main API class
- **docs/architecture.md**: full architecture documentation with sleep cycle diagrams
- **docs/sleep-guide.md**: integration guide for sleep cycle

### Changed
- Version bumped to 0.3.0

## 0.2.0 (2026-03-04)

Three-tier memory architecture, REST API, and framework integrations.

### Added
- **Three-tier architecture**: day memory (SQLite) → hot memory (markdown) → cold archive (vector embeddings)
- **Salience gating**: not every event becomes a memory — dynamic threshold with dedup guard
- **Hot memory subsystem** (`hot/`): `MemoryReader` and `MemoryWriter` for markdown-based Tier 2
- **Cold search**: find historical "echoes" during consolidation via vector similarity
- **REST API server** (`server/`): FastAPI endpoints for all AliveMemory operations
- **LangChain adapters** (`adapters/`): `AliveMessageHistory` and `AliveRetriever`
- **ElizaOS plugin** (`eliza/`): REMEMBER action + context provider
- **OpenClaw skill** (`openclaw/`): tool-use instructions for AI agents
- **Nap mode**: lightweight consolidation without cold search or dreaming
- **Backstory injection**: high-salience memory + self-knowledge file
- **Benchmark framework** (`benchmarks/`): comparative testing against 6 other memory systems
- **CI/CD**: GitHub Actions for lint, type check, and test

### Changed
- Recall uses keyword grep over markdown files (not vector search)
- Local embeddings are hash-based (deterministic, no ML dependency)
- Consolidation pipeline: moments → context → cold search → reflect → journal → embed → flush
- Version bumped to 0.2.0

## 0.1.0 (2026-02-15)

Initial scaffold.

### Added
- Core package structure: intake, recall, consolidation, identity, meta, storage, embeddings, llm
- SQLite storage backend with aiosqlite
- Config system with YAML defaults and dot-notation access
- Type system: Memory, Perception, DriveState, MoodState, CognitiveState, SelfModel
- Basic test suite
