# Changelog

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
