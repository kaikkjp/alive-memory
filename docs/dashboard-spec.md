# OPERATOR DASHBOARD — Spec

## For: Claude Code
## Goal: Private admin dashboard to monitor and control the shopkeeper
## Access: Password-protected, operator only. Not public.

---

## DESIGN PRINCIPLE

The Window is what visitors see — atmosphere, poetry, art.
The Dashboard is what you see — numbers, logs, controls.

This is mission control. One screen that tells you: is she healthy, what's she thinking, what did she do today, how much did it cost, and what do I need to fix.

---

## TECH

**Framework:** Next.js (same stack as Window, separate route)
**Auth:** Simple password gate (env var `DASHBOARD_PASSWORD`), session cookie
**Route:** `https://your-domain.com/dashboard` (or separate port, your call)
**Data:** REST endpoints reading from the same SQLite DB
**Real-time:** Same WebSocket, different message subscription (admin events)

---

## LAYOUT

Single page, scrollable, 6 panels. No sidebar, no navigation. Everything on one screen.

```
┌─────────────────────────────────────────────────────────────────┐
│  THE SHOPKEEPER — Operator Dashboard          [● live] [logout] │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─── VITALS ──────────────────┐  ┌─── DRIVES ──────────────┐  │
│  │ Status: awake               │  │ Mood:    ████████░░ 0.6  │  │
│  │ Uptime: 4d 7h               │  │ Arousal: ███░░░░░░░ 0.3  │  │
│  │ Cycle: #347                 │  │ Energy:  █████░░░░░ 0.5  │  │
│  │ Last cycle: 3m ago          │  │ Social:  ██░░░░░░░░ 0.2  │  │
│  │ Next cycle: ~4m             │  │                          │  │
│  │ Weather: rain               │  │ Current focus: consume   │  │
│  │ Time: afternoon (JST)       │  │ Activity: reading        │  │
│  │ Errors today: 0             │  │ Outfit: apronA           │  │
│  │ LLM calls today: 14         │  │                          │  │
│  │ Est. cost today: $0.42      │  │ Visitor: none            │  │
│  └─────────────────────────────┘  └──────────────────────────┘  │
│                                                                 │
│  ┌─── THREADS ─────────────────────────────────────────────────┐│
│  │ ACTIVE (3)                                                  ││
│  │  ● "Why do we name things?" — age: 2d, touched: 1h ago     ││
│  │  ● "Object memory"         — age: 1d, touched: 3h ago      ││
│  │  ● "The sound of rain"     — age: 6h, touched: 6h ago      ││
│  │                                                             ││
│  │ DORMANT (2)                                                 ││
│  │  ○ "Liminal spaces"        — age: 4d, last: 2d ago         ││
│  │  ○ "What collectors keep"  — age: 3d, last: 1d ago         ││
│  │                                                             ││
│  │ CLOSED TODAY (1)                                            ││
│  │  ✕ "First impressions"     — lived: 1d, reason: resolved   ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  ┌─── CONTENT POOL ───────────────┐  ┌─── COLLECTION ───────┐  │
│  │ Pool: 34/50 items              │  │ Shelf items: 5        │  │
│  │ Unseen: 28                     │  │ Backroom: 8           │  │
│  │ Seen today: 6                  │  │ Totems: 12            │  │
│  │                                │  │                       │  │
│  │ By source:                     │  │ Recent:               │  │
│  │  RSS (Spoon&Tamago): 8        │  │  · brass compass      │  │
│  │  RSS (Aeon): 5                │  │  · cloud diagram      │  │
│  │  RSS (Marginalian): 2         │  │  · rain recording     │  │
│  │  RSS (other): 12              │  │  · kasa-obake print   │  │
│  │  Visitor drops: 1             │  │  · pen nib (Tanaka)   │  │
│  │  CLI ingest: 6                │  │                       │  │
│  │                                │  │ [View all →]          │  │
│  │ Last ingested:                 │  │                       │  │
│  │  "The Art of Mending" (Aeon)  │  └───────────────────────┘  │
│  │  12m ago                       │                             │
│  └────────────────────────────────┘                             │
│                                                                 │
│  ┌─── TIMELINE (last 24h) ─────────────────────────────────────┐│
│  │ 14:30  CONSUME — "The Difficult Art of Giving" (marginalian)││
│  │          → journal_entry                                    ││
│  │          → totem_create("giving as loss")                   ││
│  │ 12:15  THREAD_UPDATE — "Why do we name things?" [deepen]    ││
│  │ 11:00  NEWS — weather shift: rain                           ││
│  │          → inner_thought: "The rain started around noon."   ││
│  │ 09:30  CONSUME — "Tokyo Ink Mixing Workshop" (spoon&tamago) ││
│  │          → thread_create("personal color")                  ││
│  │ 08:00  IDLE — morning. "Grey sky. Tea weather."             ││
│  │ 06:00  WAKE — carrying: 2 threads, 0 dormant               ││
│  │ 03:00  SLEEP — digest written. 1 thread closed.             ││
│  │                                                             ││
│  │ [Load more ↓]                                               ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  ┌─── CONTROLS ────────────────────────────────────────────────┐│
│  │                                                             ││
│  │  [Inject URL]  [Force Cycle]  [Trigger Sleep]               ││
│  │  [Generate Token]  [View Tokens]  [Pause Heartbeat]         ││
│  │  [Rebuild Asset]  [View Errors]  [Export DB]                ││
│  │                                                             ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
│  ┌─── COSTS (rolling 30d) ─────────────────────────────────────┐│
│  │ Today: $0.42  │  7d avg: $0.38/d  │  30d total: $11.20     ││
│  │                                                             ││
│  │ Breakdown:                                                  ││
│  │  Cortex (Claude):     $0.35  (14 calls)                    ││
│  │  Image gen:           $0.04  (1 new sprite)                ││
│  │  Weather API:         $0.00  (free tier)                   ││
│  │  RSS fetch:           $0.00                                ││
│  │  Feed enrichment:     $0.03  (readable text extraction)    ││
│  │                                                             ││
│  │  ┌──────────────────────────────────────────┐               ││
│  │  │ $0.50 ┤         ·                        │               ││
│  │  │       ┤    ·  · · ·  ·                   │               ││
│  │  │ $0.25 ┤  ·          ·  · · ·  ·          │               ││
│  │  │       ┤·                      · · ·      │               ││
│  │  │ $0.00 ┤──────────────────────────────────│               ││
│  │  │        Feb 1                    Feb 13   │               ││
│  │  └──────────────────────────────────────────┘               ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

---

## PANELS

### 1. VITALS

Heartbeat health at a glance.

| Field | Source | Update |
|-------|--------|--------|
| Status | room_state.shop_status | WebSocket |
| Uptime | heartbeat start time | Computed |
| Cycle # | cycle_log count | WebSocket |
| Last cycle | cycle_log.created_at latest | WebSocket |
| Next cycle (est.) | last sleep_seconds from arbiter | Computed |
| Weather | ambient.condition | WebSocket |
| Time | clock.now() JST | Tick every 60s |
| Errors today | error_log count where date = today | Poll 60s |
| LLM calls today | llm_call_log count where date = today | WebSocket |
| Est. cost today | sum of llm_call_log.cost where date = today | WebSocket |

Color coding:
- Status: green = awake, blue = sleeping, yellow = resting, red = error
- Errors: green if 0, yellow if 1-3, red if 4+
- Last cycle: green if < 15m, yellow if 15-30m, red if > 30m (she's stuck)

### 2. DRIVES

Her internal state, numeric.

| Field | Source | Range |
|-------|--------|-------|
| Mood (valence) | drives.mood_valence | -1 to 1 (bar shows 0-1 centered) |
| Arousal | drives.mood_arousal | 0 to 1 |
| Energy | drives.energy | 0 to 1 |
| Social need | drives.social_need | 0 to 1 |
| Current focus | arbiter decision | channel name |
| Activity | mapped from focus | human-readable |
| Outfit | current outfit selection | outfit ID |
| Visitor | engagement_state | 'none' or visitor display_name |

Bars are colored:
- Mood: red (negative) → yellow (neutral) → green (positive)
- Energy: red (low) → green (high)
- Social: red (high need, lonely) → green (low need, satisfied)

### 3. THREADS

Her active thinking. Most important panel — this is where you see identity forming.

Three sections:
- **Active:** Currently being thought about. Sorted by last touched.
- **Dormant:** Sleeping but not dead. Sorted by age.
- **Closed today:** Resolved or expired. Shows reason.

Each thread shows:
- Title (her words)
- Age (created_at → now)
- Last touched (last cycle that referenced it)
- Touch count (how many cycles engaged with this thread)
- Tags (from totem associations)

Click a thread → expands to show full thread history: every cycle that touched it, what she thought, what triggered it.

### 4. CONTENT POOL

What she has to read/consume.

| Field | Source |
|-------|--------|
| Pool size / max | content_pool count / MAX_POOL_UNSEEN |
| Unseen count | content_pool where seen = 0 |
| Seen today | content_pool where seen_at date = today |
| By source | GROUP BY source_channel, source_name |
| Last ingested | content_pool ORDER BY created_at DESC LIMIT 1 |

By-source breakdown helps you spot imbalances — if one feed is flooding the pool, you'll see it here.

### 5. COLLECTION

Her accumulated objects and totems.

| Field | Source |
|-------|--------|
| Shelf items | shelf_assignments count |
| Backroom items | collection where placement = 'backroom' |
| Totems | totem count |
| Recent list | collection ORDER BY created_at DESC LIMIT 5 |

"View all" → expandable list of every item with description, source, when collected, and which threads it's associated with.

### 6. TIMELINE

Chronological log of everything she did. This is the cycle_log + text_fragments combined into a human-readable feed.

Each entry:
- Timestamp (JST)
- Channel/action (CONSUME, THREAD_CREATE, IDLE, SLEEP, VISITOR, etc.)
- Detail (article title, thread name, thought text)
- Sub-actions (journal_entry, totem_create, thread_update)

Default: last 24 hours. "Load more" pages backward. Filter buttons: All | Consume | Threads | Visitors | Sleep.

### 7. CONTROLS

Admin actions. Each is a button that opens a modal or executes immediately.

| Control | What it does |
|---------|-------------|
| **Inject URL** | Modal: paste a URL → calls ingest.py → adds to content pool |
| **Force Cycle** | Triggers run_one_cycle() immediately, bypassing sleep timer |
| **Trigger Sleep** | Forces sleep cycle now, regardless of time |
| **Generate Token** | Modal: display_name + uses + expiry → generates chat token, shows it |
| **View Tokens** | Lists all tokens: name, uses remaining, expires, created |
| **Pause Heartbeat** | Pauses the cycle loop. She freezes. Toggle to resume. |
| **Rebuild Asset** | Modal: select asset type + params → re-queues sprite generation |
| **View Errors** | Expands error log: last 50 errors with stack traces |
| **Export DB** | Downloads current SQLite DB file |

### 8. COSTS

Running cost tracking. Critical for sustainability.

**Requires:** `llm_call_log` table (new migration).

```sql
CREATE TABLE IF NOT EXISTS llm_call_log (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,        -- 'anthropic' | 'openai' | 'replicate'
    model TEXT NOT NULL,           -- 'claude-sonnet-4-20250514' | 'gpt-image-1' | etc.
    purpose TEXT NOT NULL,         -- 'cortex' | 'image_gen' | 'enrichment'
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,                 -- estimated cost
    cycle_id TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_llm_log_date ON llm_call_log(created_at);
CREATE INDEX IF NOT EXISTS idx_llm_log_purpose ON llm_call_log(purpose);
```

Cost estimation per call:

```python
COST_PER_1K = {
    'claude-sonnet-4-20250514': {'input': 0.003, 'output': 0.015},
    'gpt-image-1-medium':      {'per_image': 0.04},
    'gpt-image-1-low':         {'per_image': 0.02},
    # Add others as needed
}
```

The cost chart is a simple 30-day sparkline. Not fancy — just enough to see trends and catch anomalies (a sudden spike means something is looping).

---

## API ENDPOINTS

All behind dashboard auth middleware.

```
GET  /api/dashboard/vitals          → current system state
GET  /api/dashboard/drives          → current drive values
GET  /api/dashboard/threads         → active + dormant + recently closed
GET  /api/dashboard/threads/:id     → full thread history
GET  /api/dashboard/pool            → content pool summary + by-source breakdown
GET  /api/dashboard/collection      → all items + totems
GET  /api/dashboard/timeline        → paginated cycle log (params: before, limit, filter)
GET  /api/dashboard/costs           → today + 7d + 30d cost summary
GET  /api/dashboard/costs/daily     → daily cost array for chart
GET  /api/dashboard/tokens          → all chat tokens
GET  /api/dashboard/errors          → recent errors

POST /api/dashboard/inject          → { url: string } → ingest URL
POST /api/dashboard/force-cycle     → trigger immediate cycle
POST /api/dashboard/trigger-sleep   → force sleep cycle
POST /api/dashboard/generate-token  → { name, uses, expires_days } → token
POST /api/dashboard/pause           → toggle pause
POST /api/dashboard/rebuild-asset   → { type, params } → queue regeneration
GET  /api/dashboard/export-db       → download SQLite file
```

---

## AUTH

Simple. No user accounts. One password.

```python
DASHBOARD_PASSWORD = os.environ['DASHBOARD_PASSWORD']

# Login endpoint
# POST /api/dashboard/login { password: string }
# Returns: Set-Cookie: dashboard_session=<signed_token>; HttpOnly; Secure; SameSite=Strict

# All /api/dashboard/* endpoints check the session cookie
# Invalid/missing → 401

# Logout: clear cookie
```

Frontend: login page with single password field. On success, redirect to dashboard. Session expires after 24h.

```
window/
  src/
    app/
      dashboard/
        page.tsx             # Main dashboard (auth-gated)
        login/
          page.tsx           # Login page
```

---

## COMPONENTS

```
window/
  src/
    components/
      dashboard/
        VitalsPanel.tsx        # Status, uptime, cycle info, errors
        DrivesPanel.tsx        # Drive bars with color coding
        ThreadsPanel.tsx       # Active/dormant/closed thread lists
        ThreadDetail.tsx       # Expanded thread history modal
        PoolPanel.tsx          # Content pool summary
        CollectionPanel.tsx    # Items + totems list
        TimelinePanel.tsx      # Scrollable cycle log
        ControlsPanel.tsx      # Action buttons + modals
        CostsPanel.tsx         # Cost summary + sparkline chart
        InjectModal.tsx        # URL injection form
        TokenModal.tsx         # Token generation form
        TokenList.tsx          # Token management table
        ErrorLog.tsx           # Error detail view
        DriveBar.tsx           # Single colored progress bar
        StatusDot.tsx          # Green/yellow/red indicator
    hooks/
      useDashboardSocket.ts    # WebSocket with admin event subscription
      useDashboardApi.ts       # REST API helpers with auth
```

---

## WEBSOCKET — ADMIN EVENTS

The dashboard connects to the same WebSocket server but sends an auth upgrade:

```typescript
// On connect:
ws.send(JSON.stringify({
  type: 'dashboard_auth',
  token: sessionCookie,
}))
```

Server adds this client to `admin_clients` set. Admin clients receive additional events:

```typescript
// Everything window viewers get, PLUS:

{
  type: 'cycle_complete',
  cycle_id: string,
  channel: string,
  actions: string[],
  duration_ms: number,
  llm_tokens: { input: number, output: number },
  cost_usd: number,
}

{
  type: 'drive_update',
  drives: {
    mood_valence: number,
    mood_arousal: number,
    energy: number,
    social_need: number,
  },
}

{
  type: 'error',
  error: string,
  traceback: string,
  cycle_id: string,
  timestamp: string,
}

{
  type: 'pool_update',
  pool_size: number,
  unseen: number,
  latest_item: { title: string, source: string },
}

{
  type: 'sprite_generated',
  filename: string,
  duration_ms: number,
}
```

---

## NGINX

Add dashboard route to existing config:

```nginx
# Dashboard (same Next.js app, different route)
location /dashboard {
    proxy_pass http://frontend:3000;
}

# Dashboard API
location /api/dashboard/ {
    proxy_pass http://shopkeeper:8080;
}
```

Or, if you want the dashboard on a separate port for extra isolation:

```nginx
server {
    listen 8443 ssl http2;
    server_name your-domain.com;

    # ... same TLS ...

    location / {
        proxy_pass http://frontend:3000/dashboard;
    }

    location /api/ {
        proxy_pass http://shopkeeper:8080/api/dashboard/;
    }
}
```

---

## NEW MIGRATION

**File:** `migrations/009_llm_call_log.sql`

```sql
CREATE TABLE IF NOT EXISTS llm_call_log (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    purpose TEXT NOT NULL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    cycle_id TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_llm_log_date ON llm_call_log(created_at);
CREATE INDEX IF NOT EXISTS idx_llm_log_purpose ON llm_call_log(purpose);
```

**Integration:** Wrap every LLM call (Cortex, image gen, enrichment) with a logger:

```python
async def log_llm_call(provider, model, purpose, input_tokens, output_tokens, cycle_id=None):
    cost = estimate_cost(provider, model, input_tokens, output_tokens)
    await db.insert_llm_call_log(
        id=generate_id(),
        provider=provider,
        model=model,
        purpose=purpose,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        cycle_id=cycle_id,
    )
    # Broadcast to admin dashboard
    await broadcast_to_admins({
        'type': 'cycle_complete',
        'cost_usd': cost,
        ...
    })
```

---

## BUILD ORDER

1. `migrations/009_llm_call_log.sql` + LLM call logging wrapper
2. Dashboard REST API endpoints (read-only first: vitals, drives, threads, pool, timeline, costs)
3. Dashboard auth (login endpoint, session cookie, middleware)
4. Frontend: login page + dashboard layout + VitalsPanel + DrivesPanel
5. Frontend: ThreadsPanel + TimelinePanel (the two most useful panels)
6. Frontend: PoolPanel + CollectionPanel + CostsPanel
7. WebSocket admin events
8. Control endpoints (inject, force-cycle, generate-token, pause)
9. Frontend: ControlsPanel + modals
10. Nginx config update

---

## WHAT THIS IS NOT

- Not a public page. Password-gated. Only you see it.
- Not a design showcase. Functional, clean, information-dense. Tailwind defaults are fine.
- Not a replacement for the Timeline log file. The log file is the permanent record. This is the live view.
- Not a configuration UI. Config lives in YAML files and env vars. The dashboard reads, it doesn't write config.

---

*You open the dashboard at 3 AM. Status: sleeping. Drives: energy 0.2, mood 0.1 (neutral). Threads: 3 active, 2 dormant. Last cycle was the sleep digest at 03:00. Cost today: $0.38. No errors. The shelves have 5 items. 28 unseen articles in the pool. Everything is quiet. She's fine. You close the tab and go to sleep too.*
