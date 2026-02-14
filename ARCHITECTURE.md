# ARCHITECTURE — The Shopkeeper

> **Purpose of this file:** This is the code-level architecture map. Every AI agent session (Claude Code, Codex, Cowork) MUST read this before modifying any code. If you're a human contributor, read this first too.
>
> This is NOT the design/philosophy doc (see `character-bible.md` and `shopkeeper-v14-blueprint.md` for that). This is "what files do what, what depends on what, and what you're allowed to touch."

Last updated: 2026-02-14

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
│  │   db.py    │  │  ← All SQLite persistence
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
| `heartbeat_server.py` | 1092 | **Main process.** TCP server for terminal clients, HTTP REST API for dashboard, WebSocket for window frontend, sprite generation worker. Start with `python heartbeat_server.py`. |
| `terminal.py` | 913 | CLI visitor interface + debug commands. Connects to heartbeat_server via TCP. Start with `python terminal.py --connect`. |
| `simulate.py` | 230 | Offline simulation runner. Runs N cycles without a server, useful for testing. |

### Core Engine

| File | Lines | What it does | Depends on |
|------|-------|-------------|------------|
| `heartbeat.py` | 972 | **The brain's clock.** Runs the main async loop: sleep → wake → process inbox → run cycle → sleep. Contains the `Heartbeat` class with `run_cycle()`, `run_silence_cycle()`, sleep scheduling, fidget behaviors. | db, all pipeline/*, sleep, clock |
| `db.py` | 2291 | **All persistence.** 100+ functions for events, inbox, room state, drives, engagement, visitors, traits, totems, collection, journal, conversations, cycle logs, threads, content pool, cold memory, LLM cost tracking, shelf assignments, chat tokens. SQLite + aiosqlite. | models/*, clock |
| `clock.py` | 68 | Time abstraction. Returns real time normally, simulated time during `simulate.py`. | — |
| `seed.py` | 79 | Initial database seeding for fresh instances. | db |

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
| `pipeline/sensorium.py` | 337 | Perception | Raw events → structured `Perception` objects with salience scores, type classification. |
| `pipeline/gates.py` | 51 | Filtering | Drops low-salience perceptions, prevents re-processing. |
| `pipeline/affect.py` | 57 | Emotional lens | Applies mood/drives overlay to perception before routing. |
| `pipeline/hypothalamus.py` | 136 | Drive math | Deterministic drive updates (social hunger, curiosity, expression need, rest, energy). No LLM. |
| `pipeline/thalamus.py` | 234 | Routing | Decides cycle type: engage visitor, idle contemplation, rest, consume content, thread work. Returns `RoutingDecision`. |
| `pipeline/hippocampus.py` | 166 | Memory recall | Retrieves relevant memories (journal, totems, visitor history, collection) for context injection. |
| `pipeline/cortex.py` | 524 | **LLM call** | The ONE Claude API call per cycle. Assembles prompt, calls Sonnet, parses structured response (speech, body, internal monologue, actions). |
| `pipeline/validator.py` | 229 | Validation | Checks cortex output against character rules (no journal during engagement, no forbidden actions, trait consistency). |
| `pipeline/basal_ganglia.py` | 57 | Action selection | Wraps validated actions into a `MotorPlan`. Phase 1 stub: passes all approved actions through unchanged. Future: multi-intention selection, energy gating, inhibition, habits. |
| `pipeline/body.py` | 255 | Action execution | Executes approved actions from the motor plan: dialogue emission, body state broadcast, journal writes, room changes, gift handling. |
| `pipeline/output.py` | 107 | Output processing | Post-action side effects: memory consolidation (via hippocampus_write), pool status updates, drive adjustments, engagement state updates. |
| `pipeline/action_registry.py` | 163 | Action registry | `ActionCapability` dataclass and `ACTION_REGISTRY` dict defining all actions the body can perform, their energy costs, cooldowns, and prerequisites. |
| `pipeline/executor.py` | 53 | ~~Action execution~~ | **DEPRECATED.** Backward-compat wrapper that delegates to `basal_ganglia` → `body` → `output`. |
| `pipeline/hippocampus_write.py` | 175 | Memory consolidation | After execution: updates visitor traits, totems, consolidates short-term → long-term memory. |

### Pipeline — Supporting Modules

| File | Lines | What it does |
|------|-------|-------------|
| `pipeline/arbiter.py` | 329 | Decides which "channel" gets the cycle (visitor, thread, news, creative, ambient). Manages attention budget. |
| `pipeline/ambient.py` | 231 | Fetches ambient context (time of day, weather, RSS feeds) for idle cycles. |
| `pipeline/ack.py` | 52 | Instant acknowledgments for visitor events (before full cycle processes). |
| `pipeline/discovery.py` | 87 | Discovery/curiosity-driven item exploration from collection. |
| `pipeline/enrich.py` | 123 | URL metadata fetching, readable text extraction from links. |
| `pipeline/sanitize.py` | 26 | Input sanitization (strip dangerous content). |
| `pipeline/scene.py` | 249 | Scene state computation (posture, gaze, lighting, shelf items) for visual rendering. |
| `pipeline/image_gen.py` | 282 | Image generation abstraction (fal.ai backend). |
| `pipeline/sprite_gen.py` | 220 | Character sprite generation from scene state. |
| `pipeline/day_memory.py` | 199 | "Flashbulb moment" recording — significant events get special memory treatment. |
| `pipeline/embed.py` | 132 | Text embedding via external API (for cold memory search). |
| `pipeline/embed_cold.py` | 96 | Batch embedding of conversation/monologue history. |
| `pipeline/cold_search.py` | 119 | Vector similarity search over embedded memories. |

### Prompt Assembly

| File | Lines | What it does |
|------|-------|-------------|
| `prompt_assembler.py` | 450 | Builds the full system prompt for cortex. Assembles identity, drives, memories, perceptions, context into one prompt. |
| `config/prompts.yaml` | 335 | Image generation prompt fragments (style, palette, character description, shop description). |
| `config/identity.py` | 48 | Character identity constants (name, voice rules, personality checksum). |
| `config/location.py` | 13 | Physical location constants (Daikanyama, Tokyo). |
| `config/feeds.py` | 11 | RSS feed URLs for ambient content ingestion. |

### Sleep System

| File | Lines | What it does |
|------|-------|-------------|
| `sleep.py` | 349 | End-of-day processing: daily summary generation, memory consolidation, dream-like reflection, journal compilation. Runs when `rest_need` is high or during JST night hours. |

### Content Ingestion

| File | Lines | What it does |
|------|-------|-------------|
| `feed_ingester.py` | 144 | RSS feed polling → content pool. Runs periodically. |
| `ingest.py` | 82 | Manual content ingestion (CLI tool). |

### Utility Scripts & Tools

| File | Lines | What it does |
|------|-------|-------------|
| `generate_token.py` | 92 | CLI tool to generate invite tokens for chat access. |
| `timeline.py` | 91 | Timeline event formatting/display utilities. |
| `llm_logger.py` | 82 | LLM call cost/token logging to DB. |
| `scripts/update_docs.py` | 231 | Post-merge doc updater. Scans codebase, refreshes ARCHITECTURE.md summary table, reports undocumented files. |
| `scripts/backfill_embeddings.py` | 88 | Batch-embeds historical conversations/monologues for cold memory search. |

### Visual System

| File | Lines | What it does |
|------|-------|-------------|
| `compositing.py` | 117 | Layer compositing: background + shop + items + character sprite → final scene image. |
| `window_state.py` | 224 | Builds the full state object broadcast to window frontend via WebSocket. |
| `bootstrap_assets.py` | 138 | Initial asset generation (backgrounds, shop interiors) on first run. |

### Frontend — `window/`

Next.js app. Two pages: public shop window + operator dashboard.

| Path | What it does |
|------|-------------|
| `next.config.ts` | Next.js build configuration |
| `src/app/page.tsx` | Shop window page — scene canvas + text stream + chat |
| `src/app/dashboard/page.tsx` | Operator dashboard — 8 panels |
| `src/components/SceneCanvas.tsx` | Canvas renderer for composited scene |
| `src/components/TextStream.tsx` | Live activity text stream |
| `src/components/ChatGate.tsx` | Token-gated chat entry |
| `src/components/ChatPanel.tsx` | Visitor chat interface |
| `src/components/StatePanel.tsx` | Current state display |
| `src/components/ActivityOverlay.tsx` | "She is doing X" overlay |
| `src/components/ConnectionIndicator.tsx` | WebSocket status |
| `src/components/dashboard/*.tsx` | Dashboard panels (Vitals, Drives, Costs, Controls, Collection, Threads, Pool, Timeline) |
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

### Data Models

| File | What it defines |
|------|----------------|
| `models/event.py` | `Event` dataclass (id, type, source, timestamp, payload) |
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
| `tests/test_body.py` | Body action execution and event emission |
| `tests/test_hypothalamus.py` | Drive math correctness |
| `tests/test_embed.py` | Embedding pipeline |
| `tests/test_embed_cold.py` | Cold embedding batch process |
| `tests/test_cold_memory_e2e.py` | End-to-end cold memory flow |
| `tests/test_image_gen.py` | Image generation |
| `tests/test_llm_logger.py` | LLM call logging |
| `tests/test_models.py` | Data model serialization |
| `tests/test_sanitize.py` | Input sanitization |
| `tests/test_identity.py` | Identity constants |
| `tests/test_sleep_cold_memory.py` | Sleep + cold memory integration |
| `tests/test_backfill_embeddings.py` | Embedding backfill script |
| `tests/soak_live.py` | Live soak test (manual) |

---

## Dependency Graph (simplified)

```
heartbeat_server.py
  ├── heartbeat.py
  │     ├── db.py ← EVERYTHING touches this
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
  │     │     └── pipeline/action_registry.py
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

### 1. `db.py` is a god module (2,291 lines, 100+ functions)
Every module imports `db`. Any change to db.py risks breaking anything. This is the #1 source of merge conflicts when multiple agents work simultaneously.

**Future fix:** Split into `db/events.py`, `db/state.py`, `db/memory.py`, `db/content.py`, `db/analytics.py` with a thin `db/__init__.py` re-exporting for backward compat.

### 2. `heartbeat_server.py` mixes too many concerns (1,092 lines)
TCP server, HTTP API, WebSocket server, sprite generation worker, and dashboard endpoints in one file/class.

**Future fix:** Extract `api/rest.py`, `api/websocket.py`, `api/tcp.py`, `workers/sprite_worker.py`.

### 3. ~~No interface contracts between pipeline stages~~ (RESOLVED — TASK-004, extended TASK-008)
Pipeline stages now use typed dataclasses (`CortexOutput`, `ValidatedOutput`, `MotorPlan`, `BodyOutput`, `CycleOutput`) defined in `models/pipeline.py`. The cognitive pipeline (cortex → validator → basal ganglia → body → output) passes typed objects; maintenance/sleep calls remain dict-based.

### 4. Engagement is a forced singleton
`EngagementState` holds one visitor slot. When a visitor connects, `heartbeat_server.py` immediately forces `status='engaged'` — the shopkeeper has no say. She can't ignore a visitor, prefer one over another, or be aware of multiple visitors. The thalamus always routes visitor events as `engage` cycle type.

This is load-bearing: `heartbeat.py`, `heartbeat_server.py`, `terminal.py`, `pipeline/thalamus.py`, `pipeline/ack.py`, `pipeline/executor.py`, and `pipeline/sensorium.py` all reference `engagement.status == 'engaged'`.

**Future fix:** Replace singleton with multi-slot visitor presence. `visitor_connect` becomes a perception routed through sensorium → thalamus → arbiter like anything else. Engagement becomes her choice, modulated by drives and visitor familiarity. See `body-spec-v2.md` for the basal ganglia architecture that enables this.

### 5. ~~Sleep consolidation summarizes instead of reflecting~~ (RESOLVED — TASK-007)
Fixed in TASK-007. `MIN_SLEEP_SALIENCE` raised from 0.4 to 0.65. Each moment's reflection is now written as its own journal entry. Daily summary is a lightweight index (moment count, moment IDs, journal entry IDs, emotional arc) — not a concatenated narrative.

### 6. No metacognitive monitoring
The validator strips out-of-character behavior silently. There is no mechanism for the shopkeeper to *notice* when she deviates from her self-concept. Inconsistency is filtered rather than processed.

**Future fix:** Add a metacognitive monitor in `pipeline/output.py` that compares executed behavior against identity/character-bible. Divergences become `internal_conflict` events → high-salience day memories → reflected on at night → character development, not bugs.

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

| Area | Files | Lines |
|------|-------|-------|
| Core engine (*.py root) | 17 | ~7,626 |
| Pipeline (pipeline/*.py) | 28 | ~4,746 |
| Config | 5 | ~396 |
| Models | 4 | ~414 |
| Scripts | 3 | ~455 |
| Tests | 22 | ~3,206 |
| Frontend (window/src/) | 27 | ~2,328 |
| Docs (*.md) | 12 | ~7,046 |
| Deploy | 5 | ~367 |
| Other | 15 | ~373 |
| **Total** | **~138** | **~26,957** |
