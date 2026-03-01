# ARCHITECTURE — The Shopkeeper

> **Purpose of this file:** This is the code-level architecture map. Every AI agent session (Claude Code, Codex, Cowork) MUST read this before modifying any code. If you're a human contributor, read this first too.
>
> This is NOT the design/philosophy doc (see `character-bible.md` and `shopkeeper-v14-blueprint.md` for that). This is "what files do what, what depends on what, and what you're allowed to touch."

Last updated: 2026-03-01

---

## System Overview

The Shopkeeper is a persistent AI character engine. One LLM call per cognitive cycle. Everything else is deterministic.

```
alive/                          ← Repository root
├── engine/                     ← Platform code (all Python)
│   ├── heartbeat_server.py     ← TCP + HTTP + WebSocket server
│   ├── heartbeat.py            ← Cognitive cycle engine
│   ├── pipeline/               ← Perception → Routing → LLM → Validation → Execution
│   ├── db/                     ← All SQLite persistence (package)
│   ├── api/                    ← HTTP route handlers
│   ├── body/                   ← External channel executors (X, Telegram, MCP, web)
│   ├── config/                 ← Python config modules
│   ├── identity/               ← Self-model, drift detection, evolution
│   ├── llm/                    ← LLM client, config, cost tracking
│   ├── metrics/                ← Liveness metrics collection
│   ├── models/                 ← Data models
│   ├── prompt/                 ← Token budget & self-context
│   ├── sleep/                  ← Sleep cycle (reflection, nap, meta-controller, wake)
│   └── workers/                ← Background workers (X poster)
├── demo/                       ← Shopkeeper instance
│   ├── config/                 ← Identity YAML, prompts YAML
│   ├── window/                 ← Next.js frontend (shop UI)
│   ├── nginx/                  ← Nginx config
│   └── content/                ← Curated reading list
├── lounge/                     ← Manager dashboard (Next.js)
├── config/                     ← Platform YAML templates (NOT Python)
├── tests/                      ← Test suite (~140 files)
├── sim/                        ← Simulation research framework
├── experiments/                ← One-off research scripts
└── scripts/                    ← Deployment, maintenance, docs
```

**Boundary rule:** `engine/` never imports from `demo/`. See `BOUNDARY.md`.

---

## Module Map

### Entry Points (the things you run)

All entry points live in `engine/` and include PYTHONPATH bootstraps.

| File | Lines | What it does |
|------|-------|-------------|
| `engine/heartbeat_server.py` | 1736 | **Main process.** TCP server for terminal clients, HTTP REST API for dashboard + public API, WebSocket for window frontend, sprite generation worker. Dashboard routes delegated to `engine/api/dashboard_routes.py`. Start with `python engine/heartbeat_server.py`. |
| `engine/terminal.py` | 1122 | CLI visitor interface + debug commands. Connects to heartbeat_server via TCP. Start with `python engine/terminal.py --connect`. |
| `engine/simulate.py` | 540 | Offline simulation runner. Runs N cycles without a server, useful for testing. |

### API Layer — `engine/api/`

| File | Lines | What it does |
|------|-------|-------------|
| `engine/api/dashboard_routes.py` | 2128 | Dashboard HTTP endpoint handlers. All `/api/dashboard/*` routes delegate here. |
| `engine/api/public_routes.py` | 287 | Public HTTP handlers for `POST /api/chat` and `GET /api/public-state` with API key auth. |
| `engine/api/api_auth.py` | 104 | API key validation and per-key rate limiting for public endpoints. |
| `engine/api/organism.py` | 48 | Pure function mapping drive/mood/energy state to visual parameters for the consciousness canvas. |

### Core Engine

All core engine modules live in `engine/`.

| File | Lines | What it does | Depends on |
|------|-------|-------------|------------|
| `engine/heartbeat.py` | 1894 | **The brain's clock.** Runs the main async loop: sleep → wake → process inbox → run cycle → sleep. Contains the `Heartbeat` class with `run_cycle()`, `run_silence_cycle()`, sleep scheduling, fidget behaviors. | db, all pipeline/*, sleep/*, clock |
| `engine/db/` | ~6,013 | **All persistence.** Package with 12 modules: `connection.py` (DB setup, migrations, transactions), `events.py` (event store, inbox), `state.py` (room/drives/engagement state), `memory.py` (visitors, traits, totems, collection, journal, day memory, cold search), `content.py` (threads, content pool, arbiter), `analytics.py` (cycle log, LLM costs, actions, habits), `social.py` (X/Twitter draft CRUD, dedup, limits), `actions.py` (dynamic action registry CRUD), `mcp.py` (MCP server registration, tool tracking), `meta_experiments.py` (meta-controller experiment log), `parameters.py` (per-cycle cached parameter loading). `__init__.py` re-exports everything for backward compatibility. SQLite + aiosqlite. | models/*, clock |
| `engine/clock.py` | 78 | Time abstraction. Returns real time normally, simulated time during `simulate.py`. | — |
| `engine/seed.py` | 115 | Initial database seeding for fresh instances. | db |
| `engine/alive_config.py` | 120 | YAML-backed configuration loader with deep-merge support for behavioral constants used across pipeline modules. | — |
| `engine/runtime_context.py` | 167 | Process-level run metadata and cycle-scoped context propagation with deterministic hashing helpers. | — |

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
| `engine/pipeline/sensorium.py` | 779 | Perception | Raw events → structured `Perception` objects with salience scores, type classification. |
| `engine/pipeline/gates.py` | 57 | Filtering | Drops low-salience perceptions, prevents re-processing. |
| `engine/pipeline/affect.py` | 51 | Emotional lens | Applies mood/drives overlay to perception before routing. |
| `engine/pipeline/hypothalamus.py` | 387 | Drive math | Deterministic drive updates (social hunger, curiosity, expression need, energy). Session tracking with social_sensitivity scaling and diminishing returns. No LLM. |
| `engine/pipeline/thalamus.py` | 352 | Routing | Decides cycle type: engage visitor, idle contemplation, consume content, thread work. Returns `RoutingDecision`. |
| `engine/pipeline/hippocampus.py` | 243 | Memory recall | Retrieves relevant memories (journal, totems, visitor history, collection) for context injection. |
| `engine/pipeline/cortex.py` | 1194 | **LLM call** | The ONE LLM API call per cycle. Assembles prompt, calls the model, parses structured response (speech, body, internal monologue, intentions). |
| `engine/pipeline/validator.py` | 136 | Validation | Checks cortex output format/schema. Character-rule enforcement is in the metacognitive monitor in output.py. |
| `engine/pipeline/basal_ganglia.py` | 900 | Action selection | Multi-intention selection from cortex intentions[]. Gates 1-6: capability, enabled, prerequisites, cooldown, energy, inhibition. Strongest intention fires, others suppressed with reasons. |
| `engine/pipeline/body.py` | 264 | Action execution | Executes approved actions from the motor plan: dialogue emission, body state broadcast, journal writes, room changes, gift handling. Delegates to `engine/body/` for external channels. |
| `engine/pipeline/output.py` | 1229 | Output processing | Post-action side effects: memory consolidation, drive adjustments, engagement state, action logging, suppression reflection, inhibition formation, habit tracking, metacognitive monitoring. |
| `engine/pipeline/action_registry.py` | 249 | Action registry | `ActionCapability` dataclass and `ACTION_REGISTRY` dict defining all actions the body can perform, their energy costs, cooldowns, and prerequisites. |
| `engine/pipeline/hippocampus_write.py` | 388 | Memory consolidation | After execution: updates visitor traits, totems, consolidates short-term → long-term memory. |
| `engine/pipeline/context_bands.py` | 61 | Context banding | Computes coarse-grained trigger context (energy band, mood band, mode, time band, visitor_present) for habit matching. |

### Pipeline — Supporting Modules

| File | Lines | What it does |
|------|-------|-------------|
| `engine/pipeline/arbiter.py` | 345 | Decides which "channel" gets the cycle (visitor, thread, news, creative, ambient). Manages attention budget. |
| `engine/pipeline/ambient.py` | 249 | Fetches ambient context (time of day, weather, RSS feeds) for idle cycles. |
| `engine/pipeline/ack.py` | 72 | Instant acknowledgments for visitor events (before full cycle processes). |
| `engine/pipeline/discovery.py` | 90 | Discovery/curiosity-driven item exploration from collection. |
| `engine/pipeline/enrich.py` | 251 | URL metadata fetching, readable text extraction from links. markdown.new integration for clean markdown conversion with fallback to HTML extraction. Content type detection (article/video/music). |
| `engine/pipeline/sanitize.py` | 24 | Input sanitization (strip dangerous content). |
| `engine/pipeline/scene.py` | 282 | Scene state computation (posture, gaze, lighting, shelf items) for visual rendering. |
| `engine/pipeline/image_gen.py` | 282 | Image generation abstraction (fal.ai backend). |
| `engine/pipeline/sprite_gen.py` | 220 | Character sprite generation from scene state. |
| `engine/pipeline/day_memory.py` | 398 | "Flashbulb moment" recording — significant events (including internal conflicts) get special memory treatment with salience boost. |
| `engine/pipeline/gap_detector.py` | 253 | Information gap scoring using embedding cosine similarity on a Goldilocks curve for curiosity triggering. |
| `engine/pipeline/habit_policy.py` | 74 | Drive-coupled habits firing as homeostatic reflexes when thresholds are met (e.g., journaling on high expression_need). |
| `engine/pipeline/notifications.py` | 129 | Surface content titles to cortex as ephemeral perceptions with cooldown tracking and salience-based sorting. |
| `engine/pipeline/embed.py` | 143 | Text embedding via external API (for cold memory search). |
| `engine/pipeline/embed_cold.py` | 99 | Batch embedding of conversation/monologue history. |
| `engine/pipeline/cold_search.py` | 132 | Vector similarity search over embedded memories. |

### Prompt Assembly — `engine/prompt/`

| File | Lines | What it does |
|------|-------|-------------|
| `engine/prompt_assembler.py` | 483 | Image generation prompt assembly. Reads `demo/config/prompts.yaml` and builds complete prompts for backgrounds, shop interiors, character sprites, items, and foreground overlays. The cortex system prompt lives in `engine/pipeline/cortex.py`. |
| `engine/prompt/budget.py` | 330 | Per-section token budget enforcement. Measures and trims prompt sections before LLM calls. Strategies: truncate_tail, drop_oldest, drop_least_relevant. |
| `engine/prompt/budget_config.json` | — | External config for per-section token caps, truncation strategies, and budget totals. |
| `engine/prompt/self_context.py` | 334 | Natural-language self-context assembler providing coherent snapshots of identity, state, behavior, and temporal awareness for prompt injection. |

### Config — `engine/config/`

| File | Lines | What it does |
|------|-------|-------------|
| `engine/config/identity.py` | 17 | Character identity constants (name, voice rules, personality checksum, machine-readable patterns for metacognitive monitor). |
| `engine/config/agent_identity.py` | 387 | Data-driven immutable identity loader from YAML. Supports world framing, embodiment, capability gating, social_sensitivity, and personality traits. |
| `engine/config/location.py` | 13 | Physical location constants (Daikanyama, Tokyo). |
| `engine/config/feeds.py` | 12 | RSS feed URLs for ambient content ingestion. |

### LLM Client — `engine/llm/`

| File | Lines | What it does |
|------|-------|-------------|
| `engine/llm/client.py` | 275 | Single entry point for all LLM completions via OpenRouter with retry logic. |
| `engine/llm/config.py` | 80 | Model resolution and API key configuration with per-call-site model override support. |
| `engine/llm/cost.py` | 89 | Cost logging for OpenRouter LLM calls with token tracking and performance metrics. |
| `engine/llm/format.py` | 133 | Bidirectional format translation between Anthropic and OpenAI/OpenRouter message shapes. |
| `engine/llm_logger.py` | 148 | LLM call cost/token logging to DB (legacy, used alongside `llm/cost.py`). |

### Identity System — `engine/identity/`

| File | Lines | What it does |
|------|-------|-------------|
| `engine/identity/self_model.py` | 407 | Persistent behavioral self-model. Tracks emergent trait weights, action frequency signatures, relational stance, and self-narrative via exponential moving averages. Updated at end of each wake cycle. Persists to `identity/self_model.json`. Read-only mirror — no decision-making. |
| `engine/identity/drift.py` | 512 | Drift detection engine comparing behavioral patterns against rolling baseline to emit behavioral divergence events. |
| `engine/identity/evolution.py` | 320 | Three-tier identity evolution engine deciding accept/correct/defer for drifted parameters based on protection rules and consciousness history. |

### Sleep System — `engine/sleep/`

| File | Lines | What it does |
|------|-------|-------------|
| `engine/sleep/__init__.py` | 171 | Sleep orchestrator re-exporting all phase functions for backward compatibility. |
| `engine/sleep/reflection.py` | 162 | Hot context gathering, per-moment LLM reflection calls, daily summary generation, and totem extraction. |
| `engine/sleep/consolidation.py` | 159 | Moment iteration, reflection via LLM, individual journal writes, and daily summary index generation during night sleep. |
| `engine/sleep/nap.py` | 83 | Lighter mid-cycle consolidation processing top moments by salience with same LLM reflection as night sleep. |
| `engine/sleep/meta_controller.py` | 642 | Metric-driven self-tuning (Tier 2) that proposes bounded parameter adjustments and evaluates their outcomes with confidence tracking. |
| `engine/sleep/meta_review.py` | 118 | Self-modification revert, trait stability updates, and auto-promotion of high-frequency pending actions. |
| `engine/sleep/wake.py` | 130 | Wake transition orchestrator managing thread lifecycle, content pool cleanup, drive reset, and cold memory embedding. |
| `engine/sleep/whisper.py` | 239 | Dream-like perception translation of pending manager config changes queued via Tier 2 sliders. |

### Memory System

| File | Lines | What it does |
|------|-------|-------------|
| `engine/memory_reader.py` | 288 | Grep-based recall from conscious Markdown memory files with keyword matching and section extraction. |
| `engine/memory_translator.py` | 233 | Conversion of drive values and mood states to natural language suitable for conscious memory writing. |
| `engine/memory_writer.py` | 292 | Append-only file writer for conscious memory with number scrubbing and structured write logging. |

### Metrics — `engine/metrics/`

| File | Lines | What it does |
|------|-------|-------------|
| `engine/metrics/collector.py` | 185 | Computes and stores liveness metrics (uptime, initiative, emotional range, entropy, knowledge) on hourly and 6-hourly schedules. |
| `engine/metrics/public.py` | 53 | Public liveness dashboard data generator for unauthenticated "proof of life" endpoint. |
| `engine/metrics/backfill.py` | 242 | Retroactive metric computation from historical cycle and action logs to populate daily metric snapshots. |
| `engine/metrics/m_uptime.py` | 55 | Uptime metric (cycles completed / expected). |
| `engine/metrics/m_initiative.py` | 76 | Initiative rate metric (self-initiated actions / total actions). |
| `engine/metrics/m_emotion.py` | 81 | Emotional range metric (mood variability). |
| `engine/metrics/m_entropy.py` | 122 | Behavioral entropy metric (action diversity). |
| `engine/metrics/m_knowledge.py` | 119 | Knowledge growth metric (new totems, threads, collection items). |
| `engine/metrics/m_memory.py` | 193 | Memory depth metric (journal entries, day memories, totem updates). |
| `engine/metrics/m_recall.py` | 108 | Recall accuracy metric (memory retrieval relevance). |
| `engine/metrics/models.py` | 36 | Metric dataclass definitions. |

### External Channel Integration — `engine/body/`

Package for external communication channels (social media, Telegram, MCP, web browsing). Not part of the cognitive pipeline — called by the pipeline's body stage.

| File | Lines | What it does |
|------|-------|-------------|
| `engine/body/executor.py` | 102 | Body executor — dispatches approved motor plan to the appropriate channel handler. |
| `engine/body/channels.py` | 67 | Channel router — routes replies to the originating channel (visitor, Telegram, X). |
| `engine/body/internal.py` | 360 | Internal action executors: dialogue emission, journal writes, room changes, gift handling. |
| `engine/body/web.py` | 159 | Web browse executor — real web search via OpenRouter `web_search` tool. |
| `engine/body/x_social.py` | 325 | X/Twitter social action execution (compose, reply, like). |
| `engine/body/x_client.py` | 174 | X/Twitter API client (tweepy wrapper). |
| `engine/body/telegram.py` | 270 | Telegram message send/receive action execution. |
| `engine/body/tg_client.py` | 80 | Telegram Bot API client. |
| `engine/body/rate_limiter.py` | 236 | Per-channel rate limiting (prevents X/Telegram API abuse). |
| `engine/body/mcp_client.py` | 213 | JSON-RPC transport client for Model Context Protocol servers with timeout and circuit breaker patterns. |
| `engine/body/mcp_executor.py` | 85 | Executor for MCP tool actions, mapping action names to server calls and logging usage. |
| `engine/body/mcp_registry.py` | 288 | Runtime-only MCP tool injection into ACTION_REGISTRY with server management and tool discovery caching. |

### Content Ingestion

| File | Lines | What it does |
|------|-------|-------------|
| `engine/feed_ingester.py` | 281 | RSS feed polling → content pool. Enriches URLs via markdown.new with content type detection. Runs periodically. |
| `engine/ingest.py` | 89 | Manual content ingestion (CLI tool). |

### Visual System

| File | Lines | What it does |
|------|-------|-------------|
| `engine/compositing.py` | 126 | Layer compositing: background + shop + items + character sprite → final scene image. |
| `engine/window_state.py` | 356 | Builds the full state object broadcast to window frontend via WebSocket. |
| `engine/bootstrap_assets.py` | 163 | Initial asset generation (backgrounds, shop interiors) on first run. |
| `engine/workers/x_poster.py` | 122 | X/Twitter integration. Posts approved drafts via tweepy, fetches replies and converts to visitor events. |

### Data Models

| File | Lines | What it defines |
|------|-------|----------------|
| `engine/models/event.py` | 37 | `Event` dataclass (id, type, source, timestamp, payload) |
| `engine/models/pipeline.py` | 380 | `CortexOutput`, `ValidatedOutput`, `MotorPlan`, `ActionDecision`, `ActionResult`, `BodyOutput`, `CycleOutput`, `SelfConsistencyResult` — typed contracts between pipeline stages |
| `engine/models/state.py` | 237 | `RoomState`, `DrivesState`, `EngagementState`, `Visitor`, `VisitorTrait`, `Totem`, `CollectionItem`, `JournalEntry`, `DailySummary`, `Thread` |

---

## Lounge — Manager Dashboard (`lounge/`)

Separate Next.js 14+ app. Multi-agent manager portal for creating, configuring, monitoring, and interacting with AI agents. Uses SQL.js (WASM) for local SQLite persistence and JWT session cookies for auth.

**Deployed at:** `/opt/alive/shopkeeper/lounge/` on VPS (systemd `alive-lounge`, port 3100).

### Pages (12)

| Path | What it does |
|------|-------------|
| `/` | Redirects to `/dashboard` |
| `/dashboard` | Agent roster — live vitals cards, create wizard. Public (soft-auth). |
| `/login` | JWT login form |
| `/agent/[id]/lounge` | **Main interaction page.** 3-column desktop layout: mind panel, consciousness canvas + state overlay + chat, I/O tabs (feed/seed/teach). Responsive mobile/tablet. |
| `/agent/[id]/configure` | Identity editor — surface (voice, boundaries), depths (drive equilibria, verbosity), capabilities (action toggles) |
| `/agent/[id]/api-keys` | API key management |
| `/agent/[id]/docs` | Agent documentation |
| `/agent/[id]/tools` | MCP servers + dynamic actions |

### Key Components (28)

| Component | What it does |
|-----------|-------------|
| `ConsciousnessCanvas.tsx` | Animated organism visualization driven by mood/drives/dreams |
| `StateOverlay.tsx` | Current action + engagement + sleep status |
| `ChatBar.tsx` | Visitor/manager message input |
| `MindPanel.tsx` | Inner voice + recent actions stream |
| `SeedTab.tsx` | Memory injection — backstory, threads, journal, totems, moments, collection |
| `FeedTab.tsx` | RSS stream management + content drops |
| `TeachTab.tsx` | Teaching/training interface |
| `MemoryPanel.tsx` / `MemoryTimeline.tsx` | Memory display components |
| `DynamicActionsPanel.tsx` | Organic actions visibility + resolve (alias/promote/reject) |
| `SettingsDrawer.tsx` | Global settings panel |
| `CreateAgentWizard.tsx` | Multi-step agent creation flow |
| `creature/` | React Three Fiber 3D creature (BodyMesh, LimbMesh, EyeMesh, physics) |
| `mcp/` | MCP server management (McpServersPanel, McpServerCard, McpConnectDialog) |

### API Routes (34)

All under `lounge/src/app/api/`. Key routes:

| Route | What it does |
|-------|-------------|
| `/agents` | List & create agents |
| `/agents/[id]/status` | Live vitals (mood, drives, engagement) — public |
| `/agents/[id]/config` | Identity management (GET/PATCH) |
| `/agents/[id]/chat` | Send visitor message |
| `/agents/[id]/stream` | SSE stream for live state |
| `/agents/[id]/whispers` | Parameter adjustments queued for sleep |
| `/agents/[id]/memories` | Inject/query episodic memories |
| `/agents/[id]/journal`, `threads`, `totems`, `collection`, `pool`, `summaries` | Memory view proxies |
| `/agents/[id]/feed/streams`, `feed/drops` | RSS stream + content management |
| `/agents/[id]/mcp/*` | MCP server management |
| `/agents/[id]/actions` | Dynamic action registry |
| `/agents/[id]/start`, `stop`, `sleep` | Container lifecycle |
| `/auth/login`, `auth/me` | JWT session management |

### Libraries

| File | Lines | What it does |
|------|-------|-------------|
| `lib/manager-db.ts` | 312 | SQL.js SQLite — managers, agents, api_keys tables |
| `lib/agent-client.ts` | 261 | HTTP proxy to agent Docker containers via localhost:{port} |
| `lib/types.ts` | 328 | 35+ TypeScript interfaces (Agent, AgentStatus, Config, Memory, Thread, Totem, McpServer, OrganismParams, etc.) |
| `lib/docker-client.ts` | 131 | Shell wrapper for agent lifecycle scripts (create, destroy, start, stop, logs) |
| `lib/auth.ts` | 65 | JWT token creation/verification |
| `middleware.ts` | 135 | JWT session validation + soft-auth for public routes. Strips spoofable `x-manager-*` headers. |
| `hooks/useAgentStream.ts` | 168 | Real-time polling hook (status every 15s, inner-voice every 20s) with connection state machine |

---

## Frontend — `demo/window/`

Next.js app (Shopkeeper instance). Two pages: public shop window + operator dashboard.

| Path | What it does |
|------|-------------|
| `demo/window/src/app/page.tsx` | Shop window page — scene canvas + text stream + chat |
| `demo/window/src/app/dashboard/page.tsx` | Operator dashboard — panels for vitals, drives, costs, controls, etc. |
| `demo/window/src/components/TextStream.tsx` | Live activity text stream |
| `demo/window/src/components/ChatGate.tsx` | Token-gated chat entry |
| `demo/window/src/components/ChatPanel.tsx` | Visitor chat interface |
| `demo/window/src/components/StatePanel.tsx` | Current state display |
| `demo/window/src/components/ActivityOverlay.tsx` | "She is doing X" overlay |
| `demo/window/src/components/ConnectionIndicator.tsx` | WebSocket status |
| `demo/window/src/components/dashboard/*.tsx` | Dashboard panels |
| `demo/window/src/hooks/useShopkeeperSocket.ts` | WebSocket connection hook |
| `demo/window/src/lib/compositor.ts` | Client-side canvas compositing |
| `demo/window/src/lib/api.ts` | REST API client |
| `demo/window/src/lib/dashboard-api.ts` | Dashboard API client |
| `demo/window/src/lib/types.ts` | TypeScript type definitions |

---

## Simulation Research Framework — `sim/`

Offline research infrastructure for running controlled experiments. Self-contained — does not depend on the production `Heartbeat` class or live DB. Used for ablation studies, liveness measurement, and architecture validation.

| File | Lines | What it does |
|------|-------|-------------|
| `sim/runner.py` | 720 | `SimulationRunner` — orchestrates N-cycle experiments with a given variant, scenario, and LLM mode. |
| `sim/variants.py` | 89 | Ablated pipeline variants: `no_drives`, `no_sleep`, `no_affect`, `no_memory`, `no_basal_ganglia`, etc. |
| `sim/scenario.py` | 148 | Scenario definitions (visitor schedules, event injection) for repeatable experimental conditions. |
| `sim/clock.py` | 90 | Simulation clock — fast-forward time without wall-clock delay. |
| `sim/db.py` | 290 | Isolated SQLite DB for simulation runs (no prod DB contamination). |
| `sim/llm/cached.py` | 212 | Cached LLM backend — replays recorded Cortex outputs (zero API cost, deterministic). |
| `sim/llm/mock.py` | 545 | Mock LLM backend — returns synthetic outputs for pure-logic testing. |
| `sim/metrics/collector.py` | 221 | Collects M1–M10 liveness metrics during simulation. |
| `sim/metrics/comparator.py` | 138 | Compares metric sets across variants. |
| `sim/metrics/exporter.py` | 143 | Exports collected metrics to JSON/CSV. |

### Experiment Harnesses — `experiments/`

| File | Lines | What it does |
|------|-------|-------------|
| `experiments/ablation_suite.py` | 483 | Full component ablation — runs all variants over N autonomous cycles and compares liveness metrics. |
| `experiments/death_spiral_survival.py` | 648 | Death spiral stress test — injects adverse conditions and measures recovery. |
| `experiments/analyze_entropy.py` | 407 | Entropy analysis of cortex outputs — measures behavioral diversity and repetition. |
| `experiments/export_cycles.py` | 133 | Exports cycle log rows to JSON for external analysis. |
| `experiments/generate_baseline.py` | 75 | Generates a baseline metric snapshot from a fresh sim run. |

---

## Deployment

| File | What it does |
|------|-------------|
| `Dockerfile` | Container build (Python 3.12-slim) |
| `docker-compose.yml` | Multi-container orchestration |
| `deploy/setup.sh` | VPS bootstrap for fresh Ubuntu 24.04 |
| `deploy/deploy.sh` | CD deploy hook (GitHub Actions) |
| `deploy/nginx.conf` | Nginx config for Docker Compose deployment |
| `deploy/shopkeeper.service` | systemd service unit |
| `deploy/backup.sh` | Daily SQLite backup |
| `deploy/init-certs.sh` | Initial Let's Encrypt TLS certificate |
| `deploy/renew-certs.sh` | Certificate renewal + nginx reload |
| `demo/nginx/shopkeeper.conf` | Production nginx config (Shopkeeper instance) |

### Scripts

| File | What it does |
|------|-------------|
| `scripts/create_agent.sh` | Create & start new agent Docker container (idempotent, `--force`, `--validate`) |
| `scripts/destroy_agent.sh` | Stop & remove agent container |
| `scripts/list_agents.sh` | Show all agent containers & status |
| `scripts/deploy-lounge.sh` | Deploy lounge to VPS (git pull + build + restart) |
| `scripts/doctor.py` | System health diagnostic (env, DB, network, ports) |
| `scripts/nginx_regen.sh` | Regenerate nginx routes from running containers |
| `scripts/scope-check.sh` | Task scope validation (checks TASK-XXX file clearance) |
| `scripts/update_docs.py` | Post-merge doc updater (refreshes ARCHITECTURE.md line counts) |
| `scripts/backfill_embeddings.py` | Batch-embeds historical conversations for cold memory search |
| `scripts/slice_counter.py` | Asset prep: slices counter foreground from shop-back.png |
| `scripts/cut_window_mask.py` | Asset prep: prepares shop interior image |

---

## Tests

~140 test files, ~42k lines. Run with `python -m pytest tests/ --tb=short -q`.

Tests mirror source modules. Key test files not obvious from names:

| File | What it tests |
|------|--------------|
| `test_basal_ganglia_selection.py` | Multi-intention selection, energy gating, cooldown, inhibition |
| `test_engagement_choice.py` | Visitor engagement as pipeline choice, not forced state |
| `test_metacognitive.py` | Self-consistency detection, internal conflict events |
| `test_meta_controller.py` | Tier 2 self-tuning parameter adjustments |
| `test_drift.py` | Behavioral drift detection against baseline |
| `test_identity_evolution.py` | Three-tier accept/correct/defer for drifted parameters |
| `test_mcp_*.py` | MCP client, registry, cortex integration, dashboard |
| `test_doctor.py` | System health checker |
| `test_sim_*.py` | Simulation framework (runner, variants, scenarios, metrics) |

**Known failure:** `test_action_read_content.py::test_read_content_cooldown` — pre-existing, ignore.

---

## Dependency Graph (simplified)

```
engine/heartbeat_server.py
  ├── engine/api/dashboard_routes.py
  ├── engine/api/public_routes.py
  ├── engine/api/api_auth.py
  ├── engine/heartbeat.py
  │     ├── engine/db/ ← EVERYTHING touches this (package)
  │     ├── engine/pipeline/sensorium.py
  │     ├── engine/pipeline/gates.py
  │     ├── engine/pipeline/affect.py
  │     ├── engine/pipeline/hypothalamus.py
  │     ├── engine/pipeline/thalamus.py
  │     ├── engine/pipeline/hippocampus.py
  │     ├── engine/pipeline/cortex.py
  │     │     ├── engine/config/agent_identity.py
  │     │     ├── engine/llm/client.py
  │     │     ├── engine/prompt/self_context.py
  │     │     └── engine/prompt/budget.py
  │     ├── engine/pipeline/validator.py
  │     ├── engine/pipeline/basal_ganglia.py
  │     ├── engine/pipeline/body.py
  │     │     ├── engine/pipeline/action_registry.py
  │     │     └── engine/body/ (channel executors + MCP)
  │     ├── engine/pipeline/output.py
  │     │     └── engine/pipeline/hippocampus_write.py
  │     ├── engine/pipeline/arbiter.py
  │     ├── engine/pipeline/ambient.py
  │     ├── engine/sleep/ (reflection, nap, meta-controller, wake)
  │     ├── engine/identity/ (self-model, drift, evolution)
  │     ├── engine/metrics/collector.py
  │     └── engine/pipeline/day_memory.py
  │
  ├── engine/pipeline/ack.py
  ├── engine/pipeline/sanitize.py (pure, no deps)
  ├── engine/pipeline/sprite_gen.py
  ├── engine/window_state.py
  ├── engine/compositing.py
  └── engine/feed_ingester.py

demo/window/ (Next.js) ← connects via WebSocket + HTTP to heartbeat_server
lounge/ (Next.js) ← connects via HTTP proxy to agent containers
```

---

## Known Architectural Debt

### 1. ~~`db.py` is a god module~~ (RESOLVED — TASK-003)
Split into `engine/db/` package with 12 modules. Zero import changes required elsewhere.

### 2. `engine/heartbeat_server.py` mixes too many concerns (1,736 lines)
TCP server, HTTP API, WebSocket server, and sprite generation worker in one file/class. Dashboard HTTP routes extracted to `engine/api/dashboard_routes.py`, public routes to `engine/api/public_routes.py`, but TCP, WebSocket, and sprite worker remain.

**Future fix:** Extract `engine/api/websocket.py`, `engine/api/tcp.py`, `engine/workers/sprite_worker.py`.

### 3. ~~No interface contracts between pipeline stages~~ (RESOLVED — TASK-004, extended TASK-008)
Pipeline stages now use typed dataclasses defined in `engine/models/pipeline.py`.

### 4. ~~Engagement is a forced singleton~~ (RESOLVED — TASK-012, TASK-013, TASK-014)
Visitor connection flows through sensorium → thalamus → arbiter as a perception competing for attention.

### 5. ~~Sleep consolidation summarizes instead of reflecting~~ (RESOLVED — TASK-007)
Each moment's reflection is now its own journal entry. Daily summary is a lightweight index.

### 6. ~~No metacognitive monitoring~~ (RESOLVED — TASK-010)
Metacognitive monitor in `engine/pipeline/output.py`. Divergences become `internal_conflict` events.

---

## Design Docs (future architecture)

| File | What it specifies |
|------|------------------|
| `body-spec-v2.md` | Brain/body split: Validator → Basal Ganglia → Body → Output pipeline. |
| `character-bible.md` | Character identity, personality, trust levels, voice rules. |
| `shopkeeper-v14-blueprint.md` | Original v1.4 cognitive architecture blueprint. |
| `docs/living-loop-spec-v2.md` | Living loop (arbiter, threads, content pool, feeds) specification. |

---

## File Count & Size Summary

> Tracked files only (`git ls-files`).

| Area | Files | Lines |
|------|-------|-------|
| Engine (`engine/**/*.py`) | ~115 | ~35,320 |
| Lounge (`lounge/src/**/*.{ts,tsx}`) | ~88 | ~13,653 |
| Tests (`tests/*.py`) | ~140 | ~41,850 |
| Scripts (`scripts/*`) | 20 | ~3,628 |
| Docs (`*.md`) | 333 | ~50,600 |
| Deploy (`deploy/*`) | 14 | ~1,096 |
| **Total tracked** | **~1,281** | **~107k** |
