# ARCHITECTURE — ALIVE Engine

> Code-level architecture map for AI agents and human contributors.
> For design philosophy see `character-bible.md` and `shopkeeper-v14-blueprint.md`.

Last generated: 2026-03-02

---

## 1. System Overview

**ALIVE** is a persistent AI character engine. One LLM call per cognitive cycle; everything else is deterministic. Python 3.12+ backend, Next.js frontend, SQLite database.

**The Shopkeeper** is the first agent built on ALIVE. She runs as a `demo/` instance. The `engine/` directory is the platform — it can host any agent via the Lounge manager dashboard.

```
alive/
├── engine/          Platform code (Python)
│   ├── pipeline/    Cognitive stages (Sensorium → Cortex → Body → Output)
│   ├── db/          All SQLite persistence (package, 12 modules)
│   ├── api/         HTTP route handlers
│   ├── body/        External channel executors (X, Telegram, MCP, web)
│   ├── config/      Python config modules
│   ├── identity/    Self-model, drift detection, evolution
│   ├── llm/         LLM client, cost tracking
│   ├── metrics/     Liveness metrics (M1–M9)
│   ├── models/      Typed data contracts
│   ├── prompt/      Token budget & self-context assembly
│   ├── sleep/       Sleep cycle (reflection, meta-controller, wake)
│   └── workers/     Background workers
├── demo/            Shopkeeper instance (identity YAML, prompts, frontend)
├── lounge/          Manager dashboard (Next.js, multi-agent)
├── config/          Platform YAML templates (NOT a Python package)
├── sim/             Simulation research framework
├── supervisor/      Platform supervisor (container lifecycle)
├── tests/           ~140 files, ~42k lines
├── experiments/     One-off research scripts
├── scripts/         Deployment, maintenance, docs
└── migrations/      28 numbered SQL migration files
```

**Boundary rule:** `engine/` never imports from `demo/`. See `BOUNDARY.md`.

---

## 2. Entry Points

| File | Purpose |
|------|---------|
| `engine/heartbeat_server.py` | **Main process.** HTTP + WebSocket + TCP server. Runs the Heartbeat in-process. |
| `engine/terminal.py` | CLI visitor interface. Standalone or connects to heartbeat_server via TCP. |
| `engine/simulate.py` | Offline simulation runner. Virtual clock, isolated DB. Requires `--db` flag. |
| `engine/gateway.py` | Multi-agent router. Agents connect via WS; Lounge sends HTTP through it. |

---

## 3. Cognitive Pipeline

Each module is one stage. They execute in order during `Heartbeat.run_cycle()`.

```
Inbox → Arbiter → Sensorium → Gates → Affect → Hypothalamus → Thalamus
                                                                   │
                                         ┌─────────────────────────┘
                                         ▼
                                    Hippocampus (recall)
                                         │
                                         ▼
                                      Cortex (single LLM call)
                                         │
                                         ▼
                                     Validator
                                         │
                                         ▼
                                  Basal Ganglia (7-gate action selection)
                                         │
                                         ▼
                                       Body (action execution)
                                         │
                                         ▼
                                      Output → hippocampus_write (memory consolidation)
```

### Pipeline Stages

| Module | Stage | Key responsibility |
|--------|-------|--------------------|
| `pipeline/arbiter.py` | Focus | Decides cycle focus channel (visitor, thread, news, express, rest, idle) |
| `pipeline/sensorium.py` | Perception | Raw events → `Perception` objects with salience scores and feature extraction |
| `pipeline/gates.py` | Filtering | Drops low-salience perceptions |
| `pipeline/affect.py` | Emotional lens | Applies mood/drives overlay; time-dilation annotations |
| `pipeline/hypothalamus.py` | Drive math | Deterministic drive updates (social_hunger, curiosity, expression_need, energy, mood). No LLM. |
| `pipeline/thalamus.py` | Routing | Maps perceptions + drives → `RoutingDecision` (cycle_type, memory_requests, token_budget) |
| `pipeline/hippocampus.py` | Memory recall | Markdown-first retrieval with SQLite fallback. Request types: visitor_summary, totems, journal, self_knowledge, etc. |
| `pipeline/cortex.py` | **LLM call** | THE single LLM call per cycle. Builds system prompt from identity, assembles user message, parses JSON → `CortexOutput`. Circuit breaker (3 failures → 5min cooldown), 500/day cap, 60s timeout. |
| `pipeline/validator.py` | Validation | Schema defaults, engagement gate, physics/hands gate, disclosure gate (strips AI tropes), entropy check |
| `pipeline/basal_ganglia.py` | Action selection | 7 gates: resolution → enabled → prerequisites → cooldown → inhibition → shop status → circuit breaker. Returns `MotorPlan`. |
| `pipeline/body.py` | Execution | Dispatches approved actions via `engine/body/` executors. Reports results to circuit breaker. |
| `pipeline/output.py` | Post-processing | Memory consolidation, drive adjustments, engagement state, inhibition formation, metacognitive monitoring |
| `pipeline/hippocampus_write.py` | Memory write | Writes to SQLite + Markdown files. Handles impressions, traits, totems, journal, threads, collection. |
| `pipeline/action_registry.py` | Registry | `ActionCapability` definitions for all ~22 registered actions (cooldowns, prerequisites, etc.) |

### Pipeline Support Modules

| Module | Purpose |
|--------|---------|
| `pipeline/ack.py` | Instant (<1s) body acknowledgment for visitor events. No LLM. |
| `pipeline/ambient.py` | Fetches weather/time ambient context for idle cycles |
| `pipeline/context_bands.py` | Coarse trigger context (energy/mood band, mode) for habit matching |
| `pipeline/day_memory.py` | Records salient "flashbulb moments" to `day_memory` table |
| `pipeline/discovery.py` | Curiosity-driven item exploration from collection |
| `pipeline/embed.py` / `embed_cold.py` | Text embedding via external API for cold memory search |
| `pipeline/cold_search.py` | Vector similarity search over embedded memories |
| `pipeline/enrich.py` | URL metadata + readable text extraction (markdown.new integration) |
| `pipeline/gap_detector.py` | Information gap scoring via embedding similarity (Goldilocks curve) |
| `pipeline/habit_policy.py` | Drive-coupled reflexive habits (e.g. journal on high expression_need) |
| `pipeline/image_gen.py` / `sprite_gen.py` | Image generation via fal.ai |
| `pipeline/notifications.py` | Surface content titles to cortex as ephemeral perceptions |
| `pipeline/sanitize.py` | Pure input sanitization |
| `pipeline/scene.py` | Deterministic state → PNG layer mapping for visual rendering |

---

## 4. Data Models (`engine/models/`)

| File | Key types |
|------|-----------|
| `models/event.py` | `Event` (id, type, source, ts, payload, channel, salience, ttl, outcome) |
| `models/state.py` | `DrivesState`, `EngagementState`, `RoomState`, `Visitor`, `VisitorTrait`, `Totem`, `CollectionItem`, `JournalEntry`, `Thread`, `EpistemicCuriosity` |
| `models/pipeline.py` | `CortexOutput`, `ValidatedOutput`, `MotorPlan`, `ActionDecision`, `ActionResult`, `BodyOutput`, `CycleOutput`, `Intention`, `ActionRequest`, `HabitBoost`, `TextFragment` |

---

## 5. Database Schema

SQLite (WAL mode) via `aiosqlite`. Write-serialized via asyncio Lock. Three separate DBs:
- `data/shopkeeper.db` — agent main DB
- `lounge/data/lounge.db` — manager dashboard (SQL.js/WASM)
- `data/supervisor.db` — platform supervisor

### Agent DB Tables

| Table | Purpose | Key columns |
|-------|---------|-------------|
| `events` | Central event store | id, event_type, source, ts, payload, channel, salience_base, salience_dynamic, ttl_hours, outcome |
| `inbox` | Unread event queue | event_id (FK), priority, read_at |
| `room_state` | Shop state (singleton) | time_of_day, weather, shop_status |
| `drives_state` | All drives (singleton) | social_hunger, curiosity, expression_need, energy, mood_valence, mood_arousal |
| `engagement_state` | Visitor engagement (singleton) | status (none/engaged/cooldown), visitor_id, turn_count |
| `visitors` | Visitor profiles | id, trust_level, visit_count, summary, emotional_imprint |
| `visitor_traits` | Per-visitor observations | visitor_id, trait_key, trait_value, confidence, stability |
| `totems` | Meaningful entities per visitor | visitor_id, entity, weight, context |
| `journal_entries` | Agent journal | content, created_at, mood, trigger |
| `collection_items` | Shelf/collection objects | name, description, source, significance |
| `conversation_log` | Per-visitor chat history | visitor_id, role, content, ts |
| `cycle_log` | Every cycle's output | cycle_type, drives_json, dialogue, actions_json, monologue |
| `day_memory` | Salient moments for sleep | cycle_id, salience, summary, processed |
| `text_fragments` | Display fragments | content, fragment_type (dialogue/thought/action), ts |
| `shelf_assignments` | Item → shelf slot mapping | item_id, slot_number |
| `threads` | Active threads of inquiry | title, status, last_touched, content |
| `content_pool` | Ingested feed items | source, content, status, fingerprint |
| `self_parameters` | ~85 runtime-tunable constants | key, value, default_value, min, max, category |
| `habits` | Learned action patterns | trigger, action, strength, context |
| `inhibitions` | Learned suppressions | action, reason, strength |
| `dynamic_actions` | Unknown actions from cortex | name, status (pending/promoted/rejected) |
| `cold_embeddings` | Vector embeddings | source_id, embedding_blob |
| `settings` | KV store for heartbeat config | key, value |
| `llm_call_log` | Every LLM call | call_site, model, tokens_in, tokens_out, cost, cycle_id |
| `metrics_snapshots` | Liveness metrics | metric_name, value, period, ts |
| `meta_experiments` | Self-tuning parameter experiments | parameter, old_value, new_value, outcome |
| `whispers` | Pending config changes for sleep | parameter, target_value, processed |

### DB Package (`engine/db/`)

| Module | Covers |
|--------|--------|
| `connection.py` | Schema, migrations, connection management, transactions |
| `events.py` | Event CRUD, inbox management |
| `state.py` | Drives, engagement, room, settings, epistemic curiosities |
| `memory.py` | Visitors, traits, totems, journal, collection, conversation, text fragments, whispers |
| `content.py` | Threads, content pool, feeds, arbiter state |
| `analytics.py` | Cycle logs, action logs, habits, inhibitions, metrics |
| `parameters.py` | Per-cycle cached parameter loading via `p(key)` |
| `actions.py` | Dynamic action registry |
| `social.py` | X/Twitter interaction tracking |
| `mcp.py` | MCP tool call logging |
| `meta_experiments.py` | Meta-controller experiment management |

Migrations live in `migrations/` (28 files, `001`–`097`). Run by `connection.py:run_migrations()`.

---

## 6. API Endpoints

### HTTP (engine/heartbeat_server.py + engine/api/)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/state` | None | Full agent state JSON |
| GET | `/api/health` | None | Liveness probe |
| GET | `/api/stats` | None | Dashboard stats |
| POST | `/api/login` | Password | Dashboard auth → Bearer token |
| GET | `/api/dashboard` | Bearer | Comprehensive dashboard JSON |
| POST | `/api/force-cycle` | Bearer | Trigger immediate cycle |
| POST | `/api/sleep` | Bearer | Force sleep |
| POST | `/api/set-interval` | Bearer | Adjust cycle interval |
| POST | `/api/message` | Bearer | Inject visitor message |
| POST | `/api/chat` | API key | External chat (await response) |
| GET | `/api/public-state` | API key | Public agent state |
| GET/POST | `/api/feeds` | Bearer | Feed management |
| GET/POST/DELETE | `/api/parameters` | Bearer | Runtime parameter tuning |
| GET/POST | `/api/habits` | Bearer | Habit management |
| GET/POST | `/api/threads` | Bearer | Thread management |
| GET | `/api/metrics` | Bearer | Liveness metric snapshots |

### WebSocket Messages (Server → Client)

| Type | Payload |
|------|---------|
| `scene_update` | Full state sync (on connect + after each cycle) |
| `text_fragment` | Incremental content (journal, thought, speech) |
| `status` | Sleep/wake state change |
| `chat_response` | Shopkeeper's chat reply |
| `chat_ack` | Message received confirmation |
| `visitor_presence` | Visitor count update |

### Gateway (engine/gateway.py)

Routes Lounge HTTP to agent WebSocket connections. Ports: HTTP 8000 (clients), WS 8001 (agents). Auth via `X-Gateway-Token` header.

---

## 7. Configuration

### YAML Config Files

| File | Purpose |
|------|---------|
| `demo/config/default_identity.yaml` | Shopkeeper character definition (voice, personality, actions, world) |
| `demo/config/prompts.yaml` | Image generation prompts (scenes, outfits, moods, weather) |
| `config/default_digital_lifeform.yaml` | Blank-slate agent template (no character, no actions) |
| `engine/prompt/budget_config.json` | Per-section token caps and truncation strategies |

### Python Config Modules

| Module | Purpose |
|--------|---------|
| `engine/config/agent_identity.py` | `AgentIdentity` frozen dataclass loaded from YAML. Search chain: env → module-relative → repo fallback. |
| `engine/config/identity.py` | Backward-compat thin wrapper re-exporting identity constants |
| `engine/alive_config.py` | `cfg(dotpath)` access to `alive_config.yaml` (~25 structural constants) |
| `engine/db/parameters.py` | `p(key)` access to `self_parameters` table (~85 runtime-tunable constants) |

### Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `OPENROUTER_API_KEY` | Yes | LLM calls via OpenRouter |
| `SHOPKEEPER_DB_PATH` | No | SQLite path (default: `data/shopkeeper.db`) |
| `COLD_SEARCH_ENABLED` | No | Vector search toggle |
| `FAL_KEY` | For visuals | fal.ai image generation |
| `OPENAI_API_KEY` | For embeddings | Text embeddings |
| `GATEWAY_URL` | For gateway mode | Gateway WebSocket URL |
| `GATEWAY_HTTP_PORT` / `GATEWAY_WS_PORT` | No | Gateway ports (default 8000/8001) |
| `LOUNGE_JWT_SECRET` | For lounge | JWT signing secret |

---

## 8. Sleep System (`engine/sleep/`)

Runs 03:00–06:00 JST. Full sequence:

1. **Whisper** — Integrate pending config changes as dream perceptions
2. **Consolidation** — Reflect on each unprocessed `day_memory` via LLM; write journal entries + daily summary
3. **Meta Review** — Trait stability, revert failed self-modifications, auto-promote improvements
4. **Meta-Controller** — Metric-driven parameter homeostasis (adjust `self_parameters` when metrics drift)
5. **Identity Evolution** — Three-tier drift resolution (accept/correct/defer)
6. **Wake** — Reset drives, flush day_memory, archive stale threads, clean content pool, reset budget

`engine/sleep/nap.py` provides a lighter mid-day consolidation (subset of moments, no meta-controller).

---

## 9. Identity System (`engine/identity/`)

| Module | Purpose |
|--------|---------|
| `self_model.py` | Persistent behavioral mirror tracking emergent traits (introversion, curiosity, warmth). Updated each cycle. Read-only — never decides. |
| `drift.py` | Detects per-parameter drift from rolling baseline |
| `evolution.py` | Three-tier evaluation: accept drift / correct back / defer decision. Rate-limited. |

---

## 10. External Channels (`engine/body/`)

| Module | Purpose |
|--------|---------|
| `executor.py` | Dispatcher routing `ActionRequest` to registered handlers |
| `internal.py` | Journal writes, gift handling, room changes, shelf management, self-modification |
| `web.py` | `browse_web` action (URL fetch + readable extraction) |
| `x_social.py` / `x_client.py` | X/Twitter posting (draft, post, reply, image) |
| `telegram.py` / `tg_client.py` | Telegram messaging |
| `channels.py` | Route replies back through originating channel |
| `rate_limiter.py` | Per-channel rate limiting |
| `mcp_client.py` / `mcp_executor.py` / `mcp_registry.py` | MCP tool integration |

---

## 11. Frontends

### Shop Window (`demo/window/`)

Next.js + TypeScript + Tailwind. Two pages: public shop window + operator dashboard.

- **WebSocket hook** (`useShopkeeperSocket.ts`): Manages connection, reconnect, all message types
- **Scene rendering**: Layered canvas (background → character → particles → glass → overlays)
- **Dashboard**: ~23 panels (vitals, drives, costs, threads, pool, parameters, drift, metrics, etc.)
- **API clients**: `api.ts` (initial state), `dashboard-api.ts` (30+ dashboard methods with Bearer auth)

### Manager Dashboard (`lounge/`)

Next.js 14+ App Router. Multi-agent portal.

- **Auth**: JWT cookies, middleware injects `x-manager-id` headers
- **DB**: SQL.js (WASM SQLite) at `lounge/data/lounge.db` — tables: `managers`, `agents`, `api_keys`
- **Agent communication**: All traffic via Gateway (`http://127.0.0.1:8000/agents/{id}/...`)
- **Key pages**: `/dashboard` (roster), `/agent/[id]/lounge` (interaction), `/agent/[id]/configure` (identity), `/agent/[id]/tools` (MCP)
- **34 API routes** under `lounge/src/app/api/` — proxies to agent containers
- **ConsciousnessCanvas**: Animated 2D organism driven by drives/mood/energy

---

## 12. Simulation & Experiments

### `sim/` — Research Framework

Self-contained. Does NOT depend on production Heartbeat. Uses in-memory SQLite.

| Module | Purpose |
|--------|---------|
| `runner.py` | `SimulationRunner` — orchestrates N-cycle experiments |
| `variants.py` | Ablated pipelines: no_drives, no_sleep, no_affect, no_basal_ganglia, no_memory |
| `scenario.py` | Repeatable conditions via YAML scenarios |
| `llm/cached.py` | Replays recorded cortex outputs (zero cost, deterministic) |
| `llm/mock.py` | Synthetic outputs for pure-logic testing |
| `metrics/` | M1–M10 collection, cross-variant comparison, JSON/CSV export |

### `experiments/` — Harnesses

| Script | Purpose |
|--------|---------|
| `ablation_suite.py` | Full component ablation across all variants |
| `death_spiral_survival.py` | Stress test: adverse conditions → recovery measurement |
| `analyze_entropy.py` | Behavioral diversity/repetition analysis |
| `generate_baseline.py` | Baseline metric snapshot generation |

---

## 13. Deployment

| File | Purpose |
|------|---------|
| `Dockerfile` | Python 3.12-slim, non-root `appuser`, ports 9999/8765/8080 |
| `docker-compose.yml` | shopkeeper + nginx + certbot |
| `deploy/` | VPS setup, CD hook, nginx, systemd, backup, TLS |

### Key Scripts

| Script | Purpose |
|--------|---------|
| `scripts/create_agent.sh` | Create Docker container for new agent (supports `--gateway`) |
| `scripts/destroy_agent.sh` | Remove agent container (`--purge` deletes data) |
| `scripts/deploy-lounge.sh` | Git-based lounge deploy to VPS |
| `scripts/doctor.py` | System health diagnostic (7 checks) |
| `scripts/scope-check.sh` | Task scope validation against `risk-policy.json` |
| `scripts/update_docs.py` | Refresh ARCHITECTURE.md line counts |

---

## 14. Key Data Flows

### Visitor Message → Response

```
WS message → sanitize → ack (body cue, <1s) → inbox_add → wake main loop
  → Sensorium (event → Perception) → Affect (mood overlay)
  → Hypothalamus (drive update) → Thalamus (route → engage cycle)
  → Hippocampus (recall visitor memories)
  → Cortex (single LLM call → CortexOutput)
  → Validator (schema + physics + disclosure)
  → Basal Ganglia (7 gates → MotorPlan)
  → Body (execute: emit dialogue, update state)
  → Output (memory consolidation, drive effects, logging)
  → WS broadcast scene_update to all viewers
```

### Autonomous Cycle (no visitor)

```
Arbiter decides focus (thread / news / express / rest / idle)
  → Sensorium (ambient perception or content notification)
  → Thalamus routes to idle/express/consume cycle type
  → Hippocampus (recall relevant context)
  → Cortex (LLM decides: journal? browse? rearrange?)
  → Basal Ganglia gates actions by energy, cooldown, inhibition
  → Body executes (journal write, web browse, content read, etc.)
  → Output consolidates memories
```

### Sleep Cycle (03:00–06:00 JST)

```
Whispers (pending config changes → dream perceptions)
  → Consolidation (day_memory moments → LLM reflection → journal)
  → Meta Review (trait stability, revert failures, auto-promote)
  → Meta-Controller (metrics → parameter adjustments)
  → Identity Evolution (accept/correct/defer drift)
  → Wake (reset drives, flush, archive threads, clean pool)
```

---

## 15. Known Issues & Architectural Debt

1. **`heartbeat_server.py` is too large** (~1,736 lines). TCP, WS, and sprite worker still mixed in. Dashboard and public routes already extracted to `engine/api/`.

2. **Known coupling**: `engine/config/feeds.py` hardcodes `demo/content/readings.txt` path (acknowledged boundary violation).

3. **Known test failure**: `test_action_read_content.py::test_read_content_cooldown` — pre-existing, ignore.

4. **`engine/pipeline/executor.py` is DEPRECATED**. Use `basal_ganglia.py` → `body.py` → `output.py`.

5. **Race condition patterns** in heartbeat: ambient/silence cycles can steal visitor events from inbox. Always check `pending_microcycle.is_set()` before background cycles. See `bugs-and-fixes.md`.

6. **Simulation safety**: `engine/db/connection.py` rejects production DB filenames. Never run `simulate.py` or `experiments/*` without `--db` pointing to an isolated path.
