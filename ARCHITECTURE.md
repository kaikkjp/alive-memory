# ARCHITECTURE — The Shopkeeper

> **Purpose of this file:** This is the code-level architecture map. Every AI agent session (Claude Code, Codex, Cowork) MUST read this before modifying any code. If you're a human contributor, read this first too.
>
> This is NOT the design/philosophy doc (see `character-bible.md` and `shopkeeper-v14-blueprint.md` for that). This is "what files do what, what depends on what, and what you're allowed to touch."

Last updated: 2026-02-21

---

## System Overview

The Shopkeeper is a persistent AI character engine. One LLM call per cognitive cycle. Everything else is deterministic.

```
Terminal/Web Client
       │
       ▼
┌──────────────────┐
│ heartbeat_server  │  ← TCP + HTTP + WebSocket server (the process you deploy)
│                  │
│  ┌────────────┐  │
│  │ Heartbeat  │  │  ← Cognitive cycle engine
│  │            │  │
│  │ ┌────────┐ │  │
│  │ │Pipeline│ │  │  ← Perception → Routing → LLM → Validation → Execution
│  │ └────────┘ │  │
│  └────────────┘  │
│                  │
│  ┌────────────┐  │
│  │    db/     │  │  ← All SQLite persistence (package)
│  └────────────┘  │
└──────────────────┘
       │
       ▼
┌──────────────────┐
│  window/ (Next.js)│  ← Public-facing "shop window" + operator dashboard
└──────────────────┘
```

---

## Module Map

### Entry Points (the things you run)

| File | Lines | What it does |
|------|-------|-------------|
| `heartbeat_server.py` | 1211 | **Main process.** TCP server for terminal clients, HTTP REST API for dashboard, WebSocket for window frontend, sprite generation worker. Dashboard routes delegated to `api/dashboard_routes.py`. Start with `python heartbeat_server.py`. |
| `terminal.py` | 1116 | CLI visitor interface + debug commands. Connects to heartbeat_server via TCP. Start with `python terminal.py --connect`. |
| `simulate.py` | 230 | Offline simulation runner. Runs N cycles without a server, useful for testing. |

### API Layer

| File | Lines | What it does |
|------|-------|-------------|
| `api/__init__.py` | 1 | Package marker. |
| `api/dashboard_routes.py` | 284 | Dashboard HTTP endpoint handlers extracted from `heartbeat_server.py` (TASK-002). All `/api/dashboard/*` routes delegate here. |

### Core Engine

| File | Lines | What it does | Depends on |
|------|-------|-------------|------------|
| `heartbeat.py` | 1087 | **The brain's clock.** Runs the main async loop: sleep → wake → process inbox → run cycle → sleep. Contains the `Heartbeat` class with `run_cycle()`, `run_silence_cycle()`, sleep scheduling, fidget behaviors. | db, all pipeline/*, sleep, clock |
| `db/` | ~3,289 | **All persistence.** Package with 8 modules: `connection.py` (DB setup, migrations, transactions), `events.py` (event store, inbox), `state.py` (room/drives/engagement state), `memory.py` (visitors, traits, totems, collection, journal, day memory, cold search), `content.py` (threads, content pool, arbiter), `analytics.py` (cycle log, LLM costs, actions, habits), `social.py` (X/Twitter draft CRUD, dedup, limits). `__init__.py` re-exports everything for backward compatibility. SQLite + aiosqlite. | models/*, clock |
| `clock.py` | 78 | Time abstraction. Returns real time normally, simulated time during `simulate.py`. | — |
| `seed.py` | 85 | Initial database seeding for fresh instances. | db |
| `workers/x_poster.py` | 122 | **X/Twitter integration.** Posts approved drafts via tweepy, fetches replies and converts to visitor events. Called from dashboard approve endpoint. | db, tweepy |

### Pipeline (the cognitive architecture)

Each module is one stage. They execute in order during a cycle. **The pipeline is the core intellectual property — modify with extreme care.**

```
Events → Inbox → Sensorium → Gates → Affect → Hypothalamus → Thalamus
                                                                  │
                                         ┌────────────────────────┘
                                         ▼
                                    Hippocampus (recall)
                                         │
                                         ▼
                                      Cortex (LLM call) ← prompt_assembler
                                         │
                                         ▼
                                     Validator
                                         │
                                         ▼
                                  Basal Ganglia (action selection)
                                         │
                                         ▼
                                       Body (action execution)
                                         │
                                         ▼
                                      Output → hippocampus_write
```

| File | Lines | Stage | What it does |
|------|-------|-------|-------------|
| `pipeline/sensorium.py` | 367 | Perception | Raw events → structured `Perception` objects with salience scores, type classification. |
| `pipeline/gates.py` | 57 | Filtering | Drops low-salience perceptions, prevents re-processing. |
| `pipeline/affect.py` | 51 | Emotional lens | Applies mood/drives overlay to perception before routing. |
| `pipeline/hypothalamus.py` | 134 | Drive math | Deterministic drive updates (social hunger, curiosity, expression need, rest, energy). No LLM. |
| `pipeline/thalamus.py` | 244 | Routing | Decides cycle type: engage visitor, idle contemplation, rest, consume content, thread work. Returns `RoutingDecision`. |
| `pipeline/hippocampus.py` | 180 | Memory recall | Retrieves relevant memories (journal, totems, visitor history, collection) for context injection. |
| `pipeline/cortex.py` | 589 | **LLM call** | The ONE Claude API call per cycle. Assembles prompt, calls Sonnet, parses structured response (speech, body, internal monologue, intentions). |
| `pipeline/validator.py` | 131 | Validation | Checks cortex output format/schema. Character-rule enforcement moved to metacognitive monitor in output.py. |
| `pipeline/basal_ganglia.py` | 395 | Action selection | Multi-intention selection from cortex intentions[]. Gates 1-6: capability, enabled, prerequisites, cooldown, energy, inhibition. Strongest intention fires, others suppressed with reasons. |
| `pipeline/body.py` | 248 | Action execution | Executes approved actions from the motor plan: dialogue emission, body state broadcast, journal writes, room changes, gift handling. |
| `pipeline/output.py` | 485 | Output processing | Post-action side effects: memory consolidation, drive adjustments, engagement state, action logging, suppression reflection, inhibition formation, habit tracking, metacognitive monitoring. |
| `pipeline/action_registry.py` | 219 | Action registry | `ActionCapability` dataclass and `ACTION_REGISTRY` dict defining all actions the body can perform, their energy costs, cooldowns, and prerequisites. |
| `pipeline/executor.py` | 53 | ~~Action execution~~ | **DEPRECATED.** Backward-compat wrapper that delegates to `basal_ganglia` → `body` → `output`. |
| `pipeline/hippocampus_write.py` | 156 | Memory consolidation | After execution: updates visitor traits, totems, consolidates short-term → long-term memory. |
| `pipeline/context_bands.py` | 61 | Context banding | Computes coarse-grained trigger context (energy band, mood band, mode, time band, visitor_present) for habit matching. |

### Pipeline — Supporting Modules

| File | Lines | What it does |
|------|-------|-------------|
| `pipeline/arbiter.py` | 329 | Decides which "channel" gets the cycle (visitor, thread, news, creative, ambient). Manages attention budget. |
| `pipeline/ambient.py` | 231 | Fetches ambient context (time of day, weather, RSS feeds) for idle cycles. |
| `pipeline/ack.py` | 69 | Instant acknowledgments for visitor events (before full cycle processes). |
| `pipeline/discovery.py` | 90 | Discovery/curiosity-driven item exploration from collection. |
| `pipeline/enrich.py` | 252 | URL metadata fetching, readable text extraction from links. markdown.new integration for clean markdown conversion with fallback to HTML extraction. Content type detection (article/video/music). |
| `pipeline/sanitize.py` | 24 | Input sanitization (strip dangerous content). |
| `pipeline/scene.py` | 249 | Scene state computation (posture, gaze, lighting, shelf items) for visual rendering. |
| `pipeline/image_gen.py` | 282 | Image generation abstraction (fal.ai backend). |
| `pipeline/sprite_gen.py` | 220 | Character sprite generation from scene state. |
| `pipeline/day_memory.py` | 213 | "Flashbulb moment" recording — significant events (including internal conflicts) get special memory treatment with salience boost. |
| `pipeline/embed.py` | 143 | Text embedding via external API (for cold memory search). |
| `pipeline/embed_cold.py` | 99 | Batch embedding of conversation/monologue history. |
| `pipeline/cold_search.py` | 132 | Vector similarity search over embedded memories. |

### Prompt Assembly

| File | Lines | What it does |
|------|-------|-------------|
| `prompt_assembler.py` | 450 | Image generation prompt assembly. Reads `config/prompts.yaml` and builds complete prompts for backgrounds, shop interiors, character sprites, items, and foreground overlays. The cortex system prompt lives in `pipeline/cortex.py`. |
| `config/prompts.yaml` | 335 | Image generation prompt fragments (style, palette, character description, shop description). |
| `config/identity.py` | 54 | Character identity constants (name, voice rules, personality checksum, machine-readable patterns for metacognitive monitor). |
| `config/location.py` | 13 | Physical location constants (Daikanyama, Tokyo). |
| `config/feeds.py` | 13 | RSS feed URLs for ambient content ingestion. |

### Token Budget — `prompt/`

| File | Lines | What it does |
|------|-------|-------------|
| `prompt/budget.py` | 317 | Per-section token budget enforcement. Measures and trims prompt sections before LLM calls. Strategies: truncate_tail, drop_oldest, drop_least_relevant. |
| `prompt/budget_config.json` | 320 | External config for per-section token caps, truncation strategies, and budget totals. Tunable without code changes. |

### Sleep System

| File | Lines | What it does |
|------|-------|-------------|
| `sleep.py` | 349 | End-of-day processing: per-moment reflective journal entries, lightweight daily summary index, memory consolidation. Runs when `rest_need` is high or during JST night hours. |

### Identity (self-model)

| File | Lines | What it does |
|------|-------|-------------|
| `identity/__init__.py` | 1 | Package marker. |
| `identity/self_model.py` | 407 | Persistent behavioral self-model. Tracks emergent trait weights, action frequency signatures, relational stance, and self-narrative via exponential moving averages. Updated at end of each wake cycle. Persists to `identity/self_model.json`. Read-only mirror — no decision-making. |

### Content Ingestion

| File | Lines | What it does |
|------|-------|-------------|
| `feed_ingester.py` | 215 | RSS feed polling → content pool. Enriches URLs via markdown.new with content type detection. Runs periodically. |
| `ingest.py` | 89 | Manual content ingestion (CLI tool). |

### Utility Scripts & Tools

| File | Lines | What it does |
|------|-------|-------------|
| `generate_token.py` | 92 | CLI tool to generate invite tokens for chat access. |
| `timeline.py` | 91 | Timeline event formatting/display utilities. |
| `llm_logger.py` | 112 | LLM call cost/token logging to DB. |
| `scripts/update_docs.py` | 235 | Post-merge doc updater. Scans codebase, refreshes ARCHITECTURE.md summary table, reports undocumented files. |
| `scripts/backfill_embeddings.py` | 88 | Batch-embeds historical conversations/monologues for cold memory search. |
| `scripts/slice_counter.py` | 68 | Asset prep: slices counter foreground from `shop-back.png` (transparent above 72%, 6px fade). |
| `scripts/cut_window_mask.py` | 48 | Asset prep: prepares shop interior image from `shop-back.png` (future: window transparency masks). |

### Visual System

| File | Lines | What it does |
|------|-------|-------------|
| `compositing.py` | 126 | Layer compositing: background + shop + items + character sprite → final scene image. |
| `window_state.py` | 240 | Builds the full state object broadcast to window frontend via WebSocket. |
| `bootstrap_assets.py` | 163 | Initial asset generation (backgrounds, shop interiors) on first run. |

### Frontend — `window/`

Next.js app. Two pages: public shop window + operator dashboard.

| Path | What it does |
|------|-------------|
| `next.config.ts` | Next.js build configuration |
| `src/app/page.tsx` | Shop window page — scene canvas + text stream + chat |
| `src/app/dashboard/page.tsx` | Operator dashboard — 13 panels |
| `src/components/SceneCanvas.tsx` | 6-layer scene compositor (scenery, shop interior, character sprite, counter foreground, vignette, dust particles) with legacy canvas fallback |
| `src/components/TextStream.tsx` | Live activity text stream |
| `src/components/ChatGate.tsx` | Token-gated chat entry |
| `src/components/ChatPanel.tsx` | Visitor chat interface |
| `src/components/StatePanel.tsx` | Current state display |
| `src/components/ActivityOverlay.tsx` | "She is doing X" overlay |
| `src/components/ConnectionIndicator.tsx` | WebSocket status |
| `src/components/dashboard/*.tsx` | Dashboard panels (Vitals, Drives, Costs, Controls, Collection, Threads, Pool, Timeline, Body, Behavioral, ContentPool, Feed, ConsumptionHistory) |
| `src/app/layout.tsx` | Next.js root layout |
| `src/hooks/useShopkeeperSocket.ts` | WebSocket connection hook |
| `src/hooks/useSceneTransition.ts` | Scene crossfade transition logic |
| `src/hooks/useParticles.ts` | Ambient particle effect hook |
| `src/lib/compositor.ts` | Client-side canvas compositing |
| `src/lib/api.ts` | REST API client |
| `src/lib/dashboard-api.ts` | Dashboard API client |
| `src/lib/types.ts` | TypeScript type definitions |
| `src/lib/auth-manager.ts` | Chat token auth |
| `src/lib/particles.ts` | Ambient particle effects |
| `src/lib/scene-constants.ts` | Scene composition constants (canvas dims, character position, z-indexes, sprite map, gradient fallbacks) |

### External Channel Integration — `body/`

Package extracted from `pipeline/body.py` for external communication channels (social media, Telegram, web browsing). Not part of the cognitive pipeline — called by the pipeline's body stage.

| File | Lines | What it does |
|------|-------|-------------|
| `body/channels.py` | 67 | Channel router — routes replies to the originating channel (visitor, Telegram, X). |
| `body/internal.py` | 360 | Internal action executors extracted from `pipeline/body.py`. Dialogue emission, journal writes, room changes, gift handling. |
| `body/web.py` | 143 | Web browse executor — real web search via OpenRouter `web_search` tool. |
| `body/x_social.py` | 298 | X/Twitter social action execution (compose, reply, like). |
| `body/x_client.py` | 174 | X/Twitter API client (tweepy wrapper). |
| `body/telegram.py` | 251 | Telegram message send/receive action execution. |
| `body/tg_client.py` | 80 | Telegram Bot API client. |
| `body/rate_limiter.py` | 185 | Per-channel rate limiting (prevents X/Telegram API abuse). |
| `body/executor.py` | 90 | Body executor — dispatches approved motor plan to the appropriate channel handler. |

### Simulation Research Framework — `sim/`

Offline research infrastructure for running controlled experiments. Self-contained — does not depend on the production `Heartbeat` class or live DB. Used for ablation studies, liveness measurement, and architecture validation.

| File | Lines | What it does |
|------|-------|-------------|
| `sim/runner.py` | 720 | `SimulationRunner` — orchestrates N-cycle experiments with a given variant, scenario, and LLM mode. Lightweight cycle loop independent of production code. |
| `sim/variants.py` | 89 | Ablated pipeline variants: `no_drives`, `no_sleep`, `no_affect`, `no_memory`, `no_basal_ganglia`, etc. Each removes one subsystem for controlled comparison. |
| `sim/scenario.py` | 148 | Scenario definitions (visitor schedules, event injection) for repeatable experimental conditions. |
| `sim/clock.py` | 90 | Simulation clock — fast-forward time without wall-clock delay. |
| `sim/db.py` | 290 | Isolated SQLite DB for simulation runs (no prod DB contamination). |
| `sim/llm/cached.py` | 212 | Cached LLM backend — replays recorded Cortex outputs (zero API cost, deterministic). |
| `sim/llm/mock.py` | 545 | Mock LLM backend — returns synthetic outputs for pure-logic testing. |
| `sim/metrics/collector.py` | 221 | Collects M1–M10 liveness metrics during simulation (uptime, initiative rate, affect variability, etc.). |
| `sim/metrics/comparator.py` | 138 | Compares metric sets across variants — identifies statistically meaningful differences. |
| `sim/metrics/exporter.py` | 143 | Exports collected metrics to JSON/CSV for analysis. |

### Experiment Harnesses — `experiments/`

One-off research scripts for specific experimental questions. Not part of the runtime. Run manually from the project root.

| File | Lines | What it does |
|------|-------|-------------|
| `experiments/ablation_suite.py` | 483 | Full component ablation — runs all variants over N autonomous cycles and compares liveness metrics. |
| `experiments/death_spiral_survival.py` | 648 | Death spiral stress test — injects adverse conditions (empty inbox, low energy, depressed affect) and measures recovery. |
| `experiments/analyze_entropy.py` | 407 | Entropy analysis of cortex outputs — measures behavioral diversity and repetition. |
| `experiments/export_cycles.py` | 133 | Exports cycle log rows to JSON for external analysis. |
| `experiments/generate_baseline.py` | 75 | Generates a baseline metric snapshot from a fresh sim run. |

### Standalone Tools — `my-agent/`

Separate Node.js code assistant built on OpenRouter SDK. Not part of the Shopkeeper runtime. Contains `agent.ts`, `cli.ts`, `tools.ts`.

### Data Models

| File | What it defines |
|------|----------------|
| `models/event.py` | `Event` dataclass (id, type, source, timestamp, payload) |
| `models/pipeline.py` | `CortexOutput`, `ValidatedOutput`, `MotorPlan`, `ActionDecision`, `ActionResult`, `BodyOutput`, `CycleOutput`, `SelfConsistencyResult` — typed contracts between pipeline stages |
| `models/state.py` | `RoomState`, `DrivesState`, `EngagementState`, `Visitor`, `VisitorTrait`, `Totem`, `CollectionItem`, `JournalEntry`, `DailySummary`, `Thread` |

### Deployment

| File | What it does |
|------|-------------|
| `Dockerfile` | Container build |
| `docker-compose.yml` | Service orchestration |
| `deploy/setup.sh` | VPS initial setup |
| `deploy/deploy.sh` | Deployment script |
| `deploy/nginx.conf` | Reverse proxy config |
| `deploy/shopkeeper.service` | systemd service |
| `deploy/backup.sh` | Database backup |
| `deploy/init-certs.sh` | TLS certificate setup |
| `deploy/renew-certs.sh` | Certificate renewal |
| `nginx/shopkeeper.conf` | Production nginx config |
| `DEPLOY_VPS.md` | Deployment instructions |

### Tests

| File | What it tests |
|------|--------------|
| `tests/test_db.py` | Database operations |
| `tests/test_db_cold_memory.py` | Cold memory storage + retrieval |
| `tests/test_cortex_timeout.py` | LLM call timeout handling |
| `tests/test_cortex_soak.py` | Extended cortex stress test |
| `tests/test_validator.py` | Response validation rules |
| `tests/test_basal_ganglia.py` | Basal ganglia stub passthrough |
| `tests/test_basal_ganglia_selection.py` | Multi-intention selection, energy gating, cooldown, inhibition |
| `tests/test_body.py` | Body action execution and event emission |
| `tests/test_hypothalamus.py` | Drive math correctness |
| `tests/test_engagement_choice.py` | Visitor engagement as pipeline choice, not forced state |
| `tests/test_embed.py` | Embedding pipeline |
| `tests/test_embed_cold.py` | Cold embedding batch process |
| `tests/test_cold_memory_e2e.py` | End-to-end cold memory flow |
| `tests/test_cors.py` | CORS origin filtering and configuration |
| `tests/test_dashboard_auth.py` | Dashboard authentication tokens and HTTP header enforcement |
| `tests/test_dashboard_routes.py` | Dashboard REST endpoint response shapes |
| `tests/test_habits.py` | Habit formation, strength curve, trigger context matching |
| `tests/test_image_gen.py` | Image generation |
| `tests/test_llm_logger.py` | LLM call logging |
| `tests/test_models.py` | Data model serialization |
| `tests/test_sanitize.py` | Input sanitization |
| `tests/test_identity.py` | Identity constants |
| `tests/test_inhibition.py` | Inhibition formation, strengthening, weakening |
| `tests/test_metacognitive.py` | Self-consistency detection, internal conflict events |
| `tests/test_multi_visitor.py` | Multi-visitor presence, attention allocation |
| `tests/test_sleep_cold_memory.py` | Sleep + cold memory integration |
| `tests/test_visitor_timeout.py` | Unengaged visitor idle timeout cleanup |
| `tests/test_window_state.py` | Window state broadcast payload |
| `tests/test_backfill_embeddings.py` | Embedding backfill script |
| `tests/test_feed_enrichment.py` | Feed enrichment via markdown.new, content type detection, fallback, dedup |
| `tests/soak_live.py` | Live soak test (manual) |
| `tests/test_sim_runner.py` | SimulationRunner — cycle execution and variant dispatch |
| `tests/test_sim_variants.py` | Ablated pipeline variants |
| `tests/test_sim_scenario.py` | Scenario definition and event injection |
| `tests/test_sim_clock.py` | Simulation clock fast-forward |
| `tests/test_sim_db.py` | Sim-isolated SQLite DB |
| `tests/test_sim_cached_cortex.py` | Cached LLM backend (replay) |
| `tests/test_sim_mock_cortex.py` | Mock LLM backend |
| `tests/test_sim_metrics.py` | M1–M10 metric collection |
| `tests/test_sim_baselines.py` | Baseline metric snapshot generation |
| `tests/test_death_spiral_survival.py` | Death spiral stress test harness |

---

## Dependency Graph (simplified)

```
heartbeat_server.py
  ├── api/dashboard_routes.py
  ├── heartbeat.py
  │     ├── db/ ← EVERYTHING touches this (package)
  │     ├── pipeline/sensorium.py
  │     ├── pipeline/gates.py
  │     ├── pipeline/affect.py
  │     ├── pipeline/hypothalamus.py
  │     ├── pipeline/thalamus.py
  │     ├── pipeline/hippocampus.py
  │     ├── pipeline/cortex.py
  │     │     ├── config/identity.py
  │     │     ├── prompt_assembler.py
  │     │     └── llm_logger.py
  │     ├── pipeline/validator.py (pure logic, imports re + models.pipeline)
  │     ├── pipeline/basal_ganglia.py (pure logic, imports models.pipeline + models.state)
  │     ├── pipeline/body.py
  │     │     ├── pipeline/action_registry.py
  │     │     └── body/ (channel executors: internal, x_social, telegram, web)
  │     ├── pipeline/output.py
  │     │     └── pipeline/hippocampus_write.py
  │     ├── pipeline/arbiter.py
  │     ├── pipeline/ambient.py
  │     ├── sleep.py
  │     └── pipeline/day_memory.py
  │
  ├── pipeline/ack.py
  ├── pipeline/sanitize.py (pure, no deps)
  ├── pipeline/sprite_gen.py
  ├── window_state.py
  ├── compositing.py
  └── feed_ingester.py

window/ (Next.js) ← connects via WebSocket + HTTP to heartbeat_server
```

---

## Known Architectural Debt

### 1. ~~`db.py` is a god module~~ (RESOLVED — TASK-003)
Split into `db/` package with 7 modules: `connection.py`, `events.py`, `state.py`, `memory.py`, `content.py`, `analytics.py`, plus `__init__.py` re-exporting everything for backward compatibility. Zero import changes required elsewhere.

### 2. `heartbeat_server.py` mixes too many concerns (1,211 lines)
TCP server, HTTP API, WebSocket server, and sprite generation worker in one file/class. Dashboard HTTP routes extracted to `api/dashboard_routes.py` (TASK-002), but TCP, WebSocket, and sprite worker remain.

**Future fix:** Extract `api/websocket.py`, `api/tcp.py`, `workers/sprite_worker.py`.

### 3. ~~No interface contracts between pipeline stages~~ (RESOLVED — TASK-004, extended TASK-008)
Pipeline stages now use typed dataclasses (`CortexOutput`, `ValidatedOutput`, `MotorPlan`, `BodyOutput`, `CycleOutput`) defined in `models/pipeline.py`. The cognitive pipeline (cortex → validator → basal ganglia → body → output) passes typed objects; maintenance/sleep calls remain dict-based.

### 4. ~~Engagement is a forced singleton~~ (RESOLVED — TASK-012, TASK-013, TASK-014)
Visitor connection no longer forces engagement. `visitor_connect` flows through sensorium → thalamus → arbiter as a perception competing for attention. Engagement is set in `pipeline/output.py` only when she actually speaks to a visitor. Multi-visitor presence via `visitors_present` table replaces the singleton. Drives (social hunger, curiosity) modulate which visitor she addresses.

### 5. ~~Sleep consolidation summarizes instead of reflecting~~ (RESOLVED — TASK-007)
Fixed in TASK-007. `MIN_SLEEP_SALIENCE` raised from 0.4 to 0.65. Each moment's reflection is now written as its own journal entry. Daily summary is a lightweight index (moment count, moment IDs, journal entry IDs, emotional arc) — not a concatenated narrative.

### 6. ~~No metacognitive monitoring~~ (RESOLVED — TASK-010)
Metacognitive monitor in `pipeline/output.py` compares executed behavior against voice rules and physical traits from `config/identity.py`. Divergences become `internal_conflict` events with salience boost in `pipeline/day_memory.py`, reflected on at night. Validator now only checks format/schema; character-rule enforcement is post-hoc detection, not silent stripping.

---

## Design Docs (future architecture)

| File | What it specifies |
|------|------------------|
| `body-spec-v2.md` | Brain/body split: Validator → Basal Ganglia → Body → Output pipeline. Action registry, inhibition system, habit formation, multi-intention cortex output. 5-phase build plan. |
| `character-bible.md` | Character identity, personality, trust levels, voice rules. |
| `shopkeeper-v14-blueprint.md` | Original v1.4 cognitive architecture blueprint. |
| `docs/living-loop-spec-v2.md` | Living loop (arbiter, threads, content pool, feeds) specification. |

---

## File Count & Size Summary

> Tracked files only (`git ls-files`). Excludes untracked local files.

| Area | Files | Lines |
|------|-------|-------|
| Core engine (*.py root) | 20 | ~7,770 |
| Pipeline (pipeline/*.py) | 32 | ~8,401 |
| API | 2 | ~1,073 |
| Config | 5 | ~428 |
| Models | 4 | ~636 |
| Scripts | 15 | ~3,021 |
| Tests | 118 | ~31,213 |
| Frontend (window/src/) | 53 | ~6,509 |
| Docs (*.md) | 51 | ~33,237 |
| Deploy | 7 | ~565 |
| **Total** | **~307** | **~92,853** | **~302** | **~91,218** | **~296** | **~89,591** |
