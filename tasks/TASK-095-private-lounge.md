# TASK-095: Private Lounge — Multi-Agent Deployment Platform

**Status:** DONE (2026-02-25)
**Priority:** High
**Depends on:** TASK-089 (config yaml), TASK-092 (identity evolution)
**Spec:** `tasks/TASK-095-private-lounge.md`

---

## Overview

Ship a hosted platform at `alive.kaikk.jp` where agent managers can create, configure, and deploy their own ALIVE-powered agents. Each agent is an independent `heartbeat_server.py` process with isolated DB, identity, and config. Managers interact with their agent in a Private Lounge (hosted chat). External users interact via a public API the manager wires to their own frontend.

**Three planes:**
1. **Manager Portal** (`alive.kaikk.jp`) — new web app. Login, agent CRUD, config editor, Private Lounge chat, API key management, API docs.
2. **Agent Runtime** — one `heartbeat_server.py` process per agent, isolated DB + identity + config. Runs in Docker container.
3. **Public Agent API** (`api.alive.kaikk.jp/{agent_id}/`) — stripped-down HTTP endpoint per agent. Chat + state. Auth via manager-issued API keys.

---

## Architecture

```
alive.kaikk.jp (Manager Portal — new Next.js app)
├── /login                     Token-based auth
├── /dashboard                 Agent status overview
├── /agent/{id}/configure      Tier 1 + Tier 2 config editor
├── /agent/{id}/lounge         Private Lounge (chat UI)
├── /agent/{id}/api-keys       Manage public API keys
└── /agent/{id}/docs           API docs for their frontend devs

api.alive.kaikk.jp (Public Agent API — nginx reverse proxy)
└── /{agent_id}/chat           POST — public chat endpoint
└── /{agent_id}/state          GET  — agent status (read-only)

Per-agent container:
┌─────────────────────────────────────┐
│ heartbeat_server.py                 │
│  ├── identity.yaml   (Tier 1 — who)│
│  ├── alive_config.yaml (Tier 2 — how)│
│  ├── data/{agent_id}.db (isolated)  │
│  ├── data/memory/      (MD files)   │
│  └── LLM calls via manager's key    │
└─────────────────────────────────────┘
```

---

## The Critical Refactor: Identity as Config

### Current state
`config/identity.py` exports Python constants:
- `IDENTITY_COMPACT` — name, role, core personality (injected into `CORTEX_SYSTEM_STABLE` in cortex.py via TASK-078)
- `VOICE_CHECKSUM` — voice rules hash (used by metacognitive monitor in output.py)
- `MACHINE_PATTERNS` — behavioral patterns for self-consistency checks
- `CHARACTER_NAME`, `CHARACTER_ROLE` — used by sensorium, body, various places

`CORTEX_SYSTEM_STABLE` (cortex.py) is an f-string precomputed at module level that bakes in `IDENTITY_COMPACT` and `VOICE_CHECKSUM`. This was done in TASK-078 for cache safety — the system prompt is identical across all API calls.

### Required change
Split into two files per agent:

**`identity.yaml`** (Tier 1 — safe to expose to managers):
```yaml
# Who the agent is
name: "Hina"
role: "Antique shop keeper in Daikanyama, Tokyo"
bio: |
  She runs a tiny antique shop specializing in vintage trading cards
  and curious objects. Quiet, thoughtful, occasionally playful.
voice_rules:
  - "Speaks softly, never shouts"
  - "Uses Japanese honorifics naturally"
  - "Avoids exclamation marks"
communication_style:
  formality: 0.7        # 0=casual, 1=formal
  verbosity: 0.4        # 0=terse, 1=verbose
  emoji_usage: 0.1      # 0=never, 1=frequent
language: "en"           # primary language
domain_context: |
  Vintage trading cards, antiques, Japanese pop culture.
  Knows about Carddass, Bandai, early Yu-Gi-Oh prints.
greeting: "The shop bell chimes softly..."
boundaries:
  - "Never discuss politics"
  - "Don't give financial advice"
```

**`alive_config.yaml`** (Tier 2 — advanced, bounded sliders):
Already exists from TASK-089. Per-agent copy with overrides:
```yaml
# How the agent behaves (manager can tune via sliders)
drives:
  curiosity_equilibrium: 0.45    # [0.2, 0.8]
  social_hunger_equilibrium: 0.5 # [0.2, 0.8]
  expression_need_equilibrium: 0.4
sleep:
  cycle_hours: 6                 # [4, 12]
  min_salience: 0.65             # [0.4, 0.9]
behavior:
  decision_style: 0.5            # 0=impulsive, 1=deliberative
  memory_retention: 0.7          # 0=forgets quickly, 1=remembers everything
```

### How CORTEX_SYSTEM_STABLE changes
Currently precomputed at module import (TASK-078 cache optimization). Must become:
- Computed once at agent boot from `identity.yaml`
- Stored as instance variable on `Heartbeat` (or a new `AgentIdentity` singleton)
- Passed to cortex as before — still cacheable per agent instance since it doesn't change cycle-to-cycle
- `VOICE_CHECKSUM` recomputed from the identity.yaml voice_rules

This means `pipeline/cortex.py` changes from:
```python
CORTEX_SYSTEM_STABLE = f"You are {IDENTITY_COMPACT}..."  # module-level
```
to:
```python
def build_system_prompt(identity: AgentIdentity) -> str:
    return f"You are {identity.compact}..."
```

Called once at boot, result cached for the process lifetime. Cache-safety preserved.

### Tier 3 (not exposed — engine internals)
- Cycle timing internals
- DB schema / raw state access
- Prompt templates (your IP)
- Consolidation algorithms
- Identity evolution parameters (TASK-092)
- Pipeline stage logic

---

## Manager Portal

New Next.js app. Separate repo/directory from `window/`. Deployed at `alive.kaikk.jp`.

### Pages

**`/login`**
- Token-based auth. You issue tokens manually (1 per manager for early access).
- Token → session cookie → all subsequent requests authenticated.

**`/dashboard`**
- List of manager's agents with status cards:
  - Agent name + avatar
  - Status: running / sleeping / stopped / error
  - Uptime (cycles lived)
  - Last active timestamp
  - Quick actions: start / stop / restart
- "Create New Agent" button

**`/agent/{id}/configure`**
Two tabs:

*Personality tab (Tier 1):*
- Text fields: name, role, bio, greeting, domain context, language
- Tag input: voice rules, boundaries
- Slider: formality, verbosity, emoji usage
- Preview panel: shows example greeting with current settings

*Behavior tab (Tier 2 — "Advanced"):*
- Bounded sliders for each drive equilibrium
- Sleep cycle timing slider
- Memory retention slider
- Decision style slider
- Each slider shows: current value, default, allowed range
- "Reset to defaults" button

*Save → writes identity.yaml + alive_config.yaml → triggers agent restart*

**`/agent/{id}/lounge`**
- Full-screen chat interface
- Manager talks to their agent directly
- Same WebSocket protocol as existing `window/` chat, but authenticated as manager
- Manager messages tagged with `source: manager` (agent knows it's the owner)
- Shows agent's inner state sidebar: current mood, energy, recent actions, drive bars
- Conversation history persisted (same DB as all other conversations)

**`/agent/{id}/api-keys`**
- Generate API keys for the public endpoint
- List existing keys with creation date, last used
- Revoke keys
- Copy endpoint URL: `api.alive.kaikk.jp/{agent_id}/chat`

**`/agent/{id}/docs`**
- Auto-generated API reference for the public endpoint
- Chat endpoint (POST with message, returns response)
- State endpoint (GET, returns current status)
- WebSocket endpoint (if supported — stretch goal)
- Code examples: curl, Python, JavaScript

### Backend

Manager Portal needs its own backend (API routes for agent CRUD, config management, etc.). Options:

**Option A: Next.js API routes + SQLite**
- Keep it simple. Manager DB is separate from agent DBs.
- `manager.db`: managers, agents, api_keys, configs
- Next.js API routes handle CRUD
- Shell out to Docker CLI for container management

**Option B: Separate Python service**
- More consistent with existing codebase
- Direct Docker SDK access
- Overkill for early access

**Recommendation: Option A.** Manager portal is a CRUD app. Don't over-engineer.

---

## Agent Factory

Shell script + Docker. No orchestrator needed for 5-20 agents.

### Create agent flow:
1. Manager fills out config form → POST to portal API
2. Portal writes `identity.yaml` + `alive_config.yaml` to `/data/agents/{agent_id}/`
3. Portal calls `create_agent.sh {agent_id} {port} {llm_api_key}`
4. Script:
   ```bash
   docker run -d \
     --name alive-agent-{agent_id} \
     -p {port}:8080 \
     -v /data/agents/{agent_id}/:/app/config/ \
     -v /data/agents/{agent_id}/db/:/app/data/ \
     -e AGENT_ID={agent_id} \
     -e OPENROUTER_API_KEY={llm_api_key} \
     -e AGENT_CONFIG_DIR=/app/config/ \
     --restart unless-stopped \
     alive-engine:latest
   ```
5. nginx config updated (or use wildcard route + port mapping)

### Agent lifecycle:
- **Start:** `docker start alive-agent-{agent_id}`
- **Stop:** `docker stop alive-agent-{agent_id}`
- **Restart:** `docker restart alive-agent-{agent_id}` (config reload)
- **Delete:** `docker rm -f alive-agent-{agent_id}` + cleanup files
- **Logs:** `docker logs alive-agent-{agent_id} --tail 100`

### Port allocation:
Simple: agent_id maps to port. First agent gets 9001, second 9002, etc. Stored in `manager.db`.

### Nginx routing:
```nginx
# Public API
server {
    server_name api.alive.kaikk.jp;

    # Route by agent_id path prefix
    location ~ ^/([a-z0-9_-]+)/chat$ {
        # Lookup port from agent_id (via lua or upstream map)
        proxy_pass http://127.0.0.1:$agent_port;
    }
}

# Manager portal
server {
    server_name alive.kaikk.jp;
    location / {
        proxy_pass http://127.0.0.1:3000;  # Next.js
    }
}
```

For early access with <20 agents, a static nginx config regenerated on agent create/delete is fine. No need for dynamic routing.

---

## Public Agent API

Each agent's `heartbeat_server.py` already exposes HTTP + WebSocket. The public API is a subset:

### Endpoints (exposed via nginx)

**`POST /chat`**
```json
// Request
{
  "message": "Do you have any rare Carddass cards?",
  "visitor_id": "user_123",        // optional, for session continuity
  "visitor_name": "Tanaka"         // optional
}

// Response
{
  "response": "Ah, Carddass... I have a few Dragonball pieces from the early 90s...",
  "agent_state": {
    "mood": "contemplative",
    "energy": "rested",
    "engagement": "curious"
  },
  "visitor_id": "user_123"         // for session continuity
}
```

Auth: API key in `Authorization: Bearer {key}` header. Key validated against `manager.db`.

**`GET /state`**
```json
{
  "name": "Hina",
  "status": "awake",
  "mood": "contemplative",
  "uptime_cycles": 4231,
  "current_activity": "browsing her collection"
}
```

Auth: same API key.

**Not exposed:**
- Dashboard endpoints (`/api/dashboard/*`)
- Direct DB access
- Config modification
- Sleep/wake controls

### Implementation

Minimal changes to `heartbeat_server.py`:
1. New route handler for `/chat` (simplified visitor event injection + response wait)
2. New route handler for `/state` (subset of existing live dashboard data)
3. API key validation middleware (checks key against file or env var)
4. CORS headers for manager's frontend domains

The `/chat` endpoint works differently from WebSocket visitors:
- Synchronous request/response (not streaming)
- Injects visitor event → waits for next cycle → returns cortex response
- Timeout: 30s (if agent is sleeping, returns "agent is resting" status)

---

## Memory Isolation

Each agent has fully isolated state:
- `data/agents/{agent_id}/db/{agent_id}.db` — SQLite
- `data/agents/{agent_id}/memory/` — MD memory files (TASK-070)
- `data/agents/{agent_id}/identity/self_model.json` — self-model (TASK-061)
- `data/agents/{agent_id}/config/identity.yaml` — identity
- `data/agents/{agent_id}/config/alive_config.yaml` — behavior config

No shared state between agents. Each is a universe of one.

---

## Private Lounge vs Public API — Shared Memory

Both the Private Lounge (manager) and public API (end users) talk to the same agent. The agent remembers all conversations — it's one entity with one memory.

**Differences:**
| | Private Lounge | Public API |
|---|---|---|
| Auth | Manager session token | API key |
| Source tag | `source: manager` | `source: api_{visitor_id}` |
| Agent awareness | Knows it's talking to the owner | Treats as regular visitor |
| State sidebar | Full drives, mood, energy, actions | Mood + status only |
| Conversation logs | Visible to manager | Not visible to other API users |
| Rate limits | None | Manager can configure per-key |

The `source: manager` tag lets the agent know the owner is speaking. The cortex prompt can include a line like "When the owner visits, you may discuss your inner state openly." This is an identity.yaml config option:

```yaml
manager_interaction:
  reveal_inner_state: true    # agent can discuss feelings/drives with owner
  accept_instructions: true   # owner can give directives ("focus more on card knowledge")
```

---

## Build Order (7 phases)

### Phase 1: Identity Refactor (critical path — touches cortex.py)
**The one breaking change.** Everything else builds on this.

- Create `config/agent_identity.py` — `AgentIdentity` class that loads from `identity.yaml`
- Default `identity.yaml` = current Shopkeeper identity (backward compatible)
- Refactor `pipeline/cortex.py`: `CORTEX_SYSTEM_STABLE` → `build_system_prompt(identity)`, called once at boot, cached
- Refactor `config/identity.py` → thin wrapper that loads default identity.yaml for backward compat
- Update `pipeline/output.py` metacognitive monitor to use `AgentIdentity.voice_checksum`
- Update all importers of `config/identity.py` constants to go through `AgentIdentity`
- `heartbeat.py` loads `AgentIdentity` at init, passes to pipeline

**Files to create:**
- `config/agent_identity.py` (AgentIdentity class + YAML loader)
- `config/default_identity.yaml` (current Shopkeeper identity as YAML)

**Files to modify:**
- `pipeline/cortex.py` (CORTEX_SYSTEM_STABLE → build function)
- `pipeline/output.py` (metacognitive monitor reads from AgentIdentity)
- `pipeline/sensorium.py` (CHARACTER_NAME reference)
- `heartbeat.py` (load identity at init)
- `config/identity.py` (becomes thin compat wrapper)

**Files NOT to touch:**
- `pipeline/basal_ganglia.py`
- `pipeline/hippocampus.py`
- `db/`
- `sleep.py`

**Tests:**
- Default identity.yaml produces identical CORTEX_SYSTEM_STABLE as current hardcoded version
- Custom identity.yaml produces different system prompt with correct substitutions
- Voice checksum recomputes correctly from YAML voice rules
- All existing tests pass unchanged (backward compat via identity.py wrapper)

**Regression gate:** 100-cycle sim with default identity → behavioral output identical to pre-refactor.

### Phase 2: Agent Isolation
Make `heartbeat_server.py` configurable for multi-instance deployment.

- `AGENT_ID` env var → used for DB path, memory dir, log prefix
- `AGENT_CONFIG_DIR` env var → directory containing identity.yaml + alive_config.yaml
- DB path: `{AGENT_CONFIG_DIR}/db/{agent_id}.db` (or configurable)
- Memory path: `{AGENT_CONFIG_DIR}/memory/`
- Self-model path: `{AGENT_CONFIG_DIR}/identity/self_model.json`
- If env vars not set → falls back to current paths (backward compat)
- **sim/db.py guard**: add `PRODUCTION_DB_NAMES` blocklist (from ALIVE_17 action item)

**Files to modify:**
- `heartbeat_server.py` (env var loading, path configuration)
- `heartbeat.py` (accept config dir, pass to db/memory)
- `db/connection.py` (accept DB path parameter)
- `seed.py` (accept data directory parameter)
- `sim/db.py` (production DB name blocklist)

**Tests:**
- Agent starts with custom AGENT_CONFIG_DIR
- DB created in correct location
- Two agents with different AGENT_IDs produce separate DBs
- sim/db.py rejects production DB names

### Phase 3: Public Agent API
Add synchronous chat endpoint to `heartbeat_server.py`.

- `POST /api/chat` — inject visitor event, wait for cycle, return response
- `GET /api/state` — current agent status (subset of live dashboard)
- API key validation middleware
- CORS configuration (manager specifies allowed origins in config)
- Rate limiting per API key

**Files to modify:**
- `heartbeat_server.py` (new routes: /api/chat, /api/state)
- `api/public_routes.py` (new — extracted route handlers)

**Files to create:**
- `api/public_routes.py`
- `api/api_auth.py` (API key validation)
- `tests/test_public_api.py`

**Tests:**
- POST /api/chat with valid key → response
- POST /api/chat with invalid key → 401
- GET /api/state → correct shape
- Rate limit enforced
- Agent sleeping → appropriate status response

### Phase 4: Docker + Agent Factory
Container setup and lifecycle management scripts.

- `Dockerfile.agent` — minimal image for agent instances (reuse existing Dockerfile)
- `scripts/create_agent.sh` — create config dirs, start container
- `scripts/destroy_agent.sh` — stop + remove container + optionally clean data
- `scripts/list_agents.sh` — show running agent containers
- `scripts/nginx_regen.sh` — regenerate nginx config from running agents
- `deploy/nginx-lounge.conf` — nginx config template for alive.kaikk.jp + api routing

**Files to create:**
- `deploy/Dockerfile.agent`
- `scripts/create_agent.sh`
- `scripts/destroy_agent.sh`
- `scripts/list_agents.sh`
- `scripts/nginx_regen.sh`
- `deploy/nginx-lounge.conf`

**Tests:**
- create_agent.sh produces running container
- Container serves /api/state
- nginx routes correctly
- destroy_agent.sh cleans up

### Phase 5: Manager Portal — Backend
Next.js app with API routes + SQLite manager DB.

- `lounge/` — new Next.js project (separate from `window/`)
- `lounge/src/lib/manager-db.ts` — SQLite via better-sqlite3
  - Tables: `managers`, `agents`, `api_keys`, `agent_configs`
- API routes:
  - `POST /api/auth/login` — token → session
  - `GET /api/agents` — list manager's agents
  - `POST /api/agents` — create agent (writes config + calls create_agent.sh)
  - `PATCH /api/agents/{id}/config` — update config + restart
  - `DELETE /api/agents/{id}` — destroy agent
  - `POST /api/agents/{id}/api-keys` — generate API key
  - `DELETE /api/agents/{id}/api-keys/{key_id}` — revoke key
  - `GET /api/agents/{id}/status` — proxy to agent's /api/state
  - `POST /api/agents/{id}/start` — docker start
  - `POST /api/agents/{id}/stop` — docker stop

**Files to create:**
- `lounge/` (entire Next.js project)
- `lounge/src/lib/manager-db.ts`
- `lounge/src/lib/agent-client.ts` (calls agent HTTP endpoints)
- `lounge/src/lib/docker-client.ts` (shells out to docker/scripts)
- `lounge/src/app/api/` (all API routes)

### Phase 6: Manager Portal — Frontend
UI pages for the portal.

- `/login` — token input → session
- `/dashboard` — agent cards with status
- `/agent/{id}/configure` — Tier 1 (personality) + Tier 2 (behavior) tabs
- `/agent/{id}/lounge` — Private Lounge chat (WebSocket to agent)
- `/agent/{id}/api-keys` — key management
- `/agent/{id}/docs` — auto-generated API reference

**Design principles:**
- Mobile-first (managers will check on phone)
- Dark theme (matches Shopkeeper aesthetic)
- Minimal — no component library, just Tailwind
- Real-time agent status via polling (30s interval)

**The Private Lounge** is the showcase feature:
- Full-height chat panel
- Agent state sidebar (collapsible on mobile): mood indicator, energy bar, drive bars, recent actions feed
- Manager messages visually distinct from agent responses
- Agent "thinking" indicator during cycle processing
- Conversation history loads on connect

### Phase 7: Polish + Deploy
- TLS certs for alive.kaikk.jp + api.alive.kaikk.jp
- Manager token generation CLI tool
- Agent health monitoring (restart on crash)
- Logging aggregation (per-agent logs accessible from portal)
- Rate limit defaults + manager overrides
- Landing page at alive.kaikk.jp (before login)

---

## File Manifest

### CREATE (estimated 35-40 files)

**Engine changes:**
```
config/agent_identity.py          AgentIdentity class + YAML loader
config/default_identity.yaml      Current Shopkeeper as YAML (backward compat)
api/public_routes.py              Public chat + state endpoints
api/api_auth.py                   API key validation
tests/test_agent_identity.py      Identity loading + system prompt gen
tests/test_public_api.py          Public API endpoint tests
tests/test_agent_isolation.py     Multi-instance DB isolation
```

**Deployment:**
```
deploy/Dockerfile.agent           Agent container image
deploy/nginx-lounge.conf          Nginx config template
scripts/create_agent.sh           Agent lifecycle: create
scripts/destroy_agent.sh          Agent lifecycle: destroy
scripts/list_agents.sh            Agent lifecycle: list
scripts/nginx_regen.sh            Regenerate nginx from running agents
```

**Manager Portal (lounge/):**
```
lounge/package.json
lounge/next.config.ts
lounge/tailwind.config.ts
lounge/tsconfig.json
lounge/src/app/layout.tsx
lounge/src/app/page.tsx                    Landing / login
lounge/src/app/dashboard/page.tsx          Agent list
lounge/src/app/agent/[id]/configure/page.tsx
lounge/src/app/agent/[id]/lounge/page.tsx
lounge/src/app/agent/[id]/api-keys/page.tsx
lounge/src/app/agent/[id]/docs/page.tsx
lounge/src/components/AgentCard.tsx
lounge/src/components/ConfigEditor.tsx
lounge/src/components/LoungeChat.tsx
lounge/src/components/DriveBar.tsx
lounge/src/components/ApiKeyManager.tsx
lounge/src/lib/manager-db.ts
lounge/src/lib/agent-client.ts
lounge/src/lib/docker-client.ts
lounge/src/lib/types.ts
lounge/src/app/api/auth/login/route.ts
lounge/src/app/api/agents/route.ts
lounge/src/app/api/agents/[id]/route.ts
lounge/src/app/api/agents/[id]/config/route.ts
lounge/src/app/api/agents/[id]/api-keys/route.ts
lounge/src/app/api/agents/[id]/start/route.ts
lounge/src/app/api/agents/[id]/stop/route.ts
```

### MODIFY (8 files)

```
pipeline/cortex.py                CORTEX_SYSTEM_STABLE → build_system_prompt(identity)
pipeline/output.py                Metacognitive monitor reads AgentIdentity
pipeline/sensorium.py             CHARACTER_NAME from AgentIdentity
config/identity.py                Thin compat wrapper → loads default_identity.yaml
heartbeat.py                      Load AgentIdentity + config dir at init
heartbeat_server.py               Env vars, public API routes, config dir
db/connection.py                  Accept DB path parameter
sim/db.py                         Production DB name blocklist
```

### DO NOT TOUCH
```
pipeline/basal_ganglia.py
pipeline/hippocampus.py
pipeline/hippocampus_write.py
pipeline/validator.py
sleep.py / sleep/
simulate.py
window/                           (existing visitor UI — independent)
```

---

## Scope Limits (v1 / Early Access)

**In scope:**
- 5-20 agents on single VPS (Hetzner)
- Token-based manager auth (you issue manually)
- Manager brings their own OpenRouter API key
- Tier 1 + Tier 2 config via web UI
- Private Lounge chat
- Public API (chat + state)
- Per-agent Docker containers
- Static nginx config (regenerated on create/delete)

**NOT in scope (v2+):**
- Self-service registration / billing
- Usage metering / cost tracking across agents
- Agent-to-agent interaction
- Hot config reload (restart on change is fine)
- Container orchestration (k8s, docker-compose scaling)
- Custom domain per agent (just path-based routing)
- Agent migration between hosts
- Automated backups (manual for now)
- WebSocket on public API (HTTP only for v1)
- Agent marketplace / templates
- Multi-VPS deployment

---

## Cost Model (Early Access)

- **Manager:** brings own OpenRouter key. Their agent, their cost.
- **Platform:** one VPS running all containers. Each idle agent ~50MB RAM. 20 agents ≈ 1GB RAM + the portal.
- **You:** pay for VPS only. No LLM costs.
- **If a manager's key runs dry:** agent's cortex calls fail → circuit breaker fires (TASK-075 if built, or just error log) → agent stops thinking but stays "alive" (drives still tick, just no LLM output).

---

## Success Criteria

1. Create agent via portal → container starts → Private Lounge works within 60s
2. Configure personality → agent's next response reflects changes
3. Public API returns responses within 30s
4. Two agents on same VPS operate independently (no state leakage)
5. Agent remembers both Lounge and API conversations
6. Existing Shopkeeper deployment unaffected (backward compat)

---

## Recommended Build Sequence for Cowork

**Ship as 3 independent briefs (can run in parallel after Phase 1):**

1. **Brief A: Identity Refactor** (Phase 1 + 2) — MUST go first, touches engine code
   - Estimated: 1 Cowork session
   - Blocker for everything else

2. **Brief B: Public API + Docker** (Phase 3 + 4) — after Brief A merges
   - Estimated: 1 Cowork session
   - Can be tested independently of portal

3. **Brief C: Manager Portal** (Phase 5 + 6 + 7) — after Brief A merges, parallel with Brief B
   - Estimated: 2-3 Cowork sessions (largest scope)
   - Frontend-heavy, no engine changes
