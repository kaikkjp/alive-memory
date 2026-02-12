# THE LIVING LOOP — Architecture Spec

## For: Claude Code / Cowork
## Goal: Give the shopkeeper autonomous inner life through four input channels + cycle arbiter

---

## DESIGN PRINCIPLES

She is treated as human. Humans have multiple input channels operating at different cadences, with different levels of agency. She should too.

The system today is reactive — she only thinks when visitors trigger cycles. The Living Loop makes her proactive: she notices things, chooses what to consume, feels her environment, and carries thoughts across days.

**One rule above all: no extra LLM calls.** The existing single-Cortex-call-per-cycle architecture stays. The Living Loop gives her better *material* to think about, not more thinking.

**Second rule: no new pipeline modes.** The existing mode set (`engage`, `express`, `idle`, `rest`, `maintenance`) is the only contract Thalamus, Validator, and Cortex understand. The arbiter introduces *focus channels* (`consume`, `thread`, `news`) which are arbiter-level concepts that map to existing pipeline modes. This avoids touching the mode enum, validator checks, or cortex routing tables. The focus channel rides as metadata alongside the mode, influencing perception construction and prompt framing but not pipeline control flow.

---

## ARCHITECTURE OVERVIEW

```
                    ┌─────────────────────┐
                    │    CYCLE ARBITER     │
                    │  (per-cycle planner) │
                    └─────────┬───────────┘
                              │ picks exactly ONE focus
              ┌───────┬───────┼───────┬────────┐
              │       │       │       │        │
         ┌────▼──┐ ┌──▼───┐ ┌▼────┐ ┌▼─────┐ ┌▼──────┐
         │VISITOR│ │ NEWS │ │READ │ │AMBI- │ │THREAD │
         │(chat) │ │/EVENT│ │/LIST│ │ ENT  │ │(inner)│
         └───────┘ └──────┘ └─────┘ └──────┘ └───────┘
              │       │       │       │        │
              └───────┴───────┴───┬───┴────────┘
                                  │
                    ┌─────────────▼───────────┐
                    │   EXISTING PIPELINE     │
                    │ Sensorium → Thalamus →  │
                    │ Hippocampus → Cortex →  │
                    │ Validator → Executor    │
                    └─────────────────────────┘
```

---

## 1. CYCLE ARBITER

**File:** `pipeline/arbiter.py`

The arbiter runs at the TOP of every non-visitor cycle. It decides what the cycle is *for* before perceptions are built.

### Decision Logic (deterministic, no LLM)

```
Priority order:
  1. Visitor engaged → VISITOR (bypass arbiter entirely)
  2. Rest guard (rest_need > 0.8 OR energy < 0.2) → REST
  3. Active thread with deadline today → THREAD
  4. Unread high-salience news (effective_salience > 0.5, age < 2hr) → NEWS
  5. Reading urge (curiosity > 0.5 AND consume cooldown elapsed AND consume budget available) → CONSUME
  6. Active thread (highest priority, touched least recently, thread cooldown elapsed) → THREAD
  7. Unread news exists (news cooldown elapsed and budget available) → NEWS
  8. Creative pressure (expression_need > 0.6 OR creative_overdue) AND express cooldown elapsed → EXPRESS
  9. Default → AMBIENT_IDLE (existing behavior)
```

Tie-breakers are deterministic:
- First by priority rule order above
- Then by higher score within channel (priority/salience)
- Then oldest `created_at`
- Then lexical `id` (stable final tie-break)

### Hard Caps (per JST day)

| Resource | Cap | Rationale |
|----------|-----|-----------|
| Cortex cycles (total) | 500 | Already exists |
| Consume cycles | 3/day | She doesn't binge. Identity forms slowly. |
| News engagements | 10/day | Most news washes over her. |
| Thread focus cycles | 8/day | She's contemplative, not a productivity machine. |
| Express cycles | 6/day | Already gated by 2hr cooldown |

### Per-Channel Cooldowns

| Channel | Cooldown | Notes |
|---------|----------|-------|
| Consume | 2 hours | She needs time to sit with what she read/heard |
| News engage | 30 min | She doesn't doomscroll |
| Thread focus | 45 min | She doesn't obsess (unless mood_arousal > 0.7) |
| Express | 2 hours | Already exists |

### Novelty Penalty

Track last 20 focus topics (keywords from perception content). If a new item shares >60% keyword overlap with recent focuses, reduce its priority by 0.3. Prevents same-topic loops.

### State Tracking

```python
@dataclass
class ArbiterState:
    consume_count_today: int = 0
    news_engage_count_today: int = 0
    thread_focus_count_today: int = 0
    express_count_today: int = 0
    last_consume_ts: Optional[datetime] = None
    last_news_engage_ts: Optional[datetime] = None
    last_thread_focus_ts: Optional[datetime] = None
    last_express_ts: Optional[datetime] = None
    recent_focus_keywords: list[str] = field(default_factory=list)  # last 20
    current_date_jst: str = ''  # resets caps on new day
```

Persist this state to SQLite so restart does not reset caps/cooldowns:

```sql
CREATE TABLE IF NOT EXISTS arbiter_state (
    singleton_key INTEGER PRIMARY KEY CHECK (singleton_key = 1),
    consume_count_today INTEGER NOT NULL DEFAULT 0,
    news_engage_count_today INTEGER NOT NULL DEFAULT 0,
    thread_focus_count_today INTEGER NOT NULL DEFAULT 0,
    express_count_today INTEGER NOT NULL DEFAULT 0,
    last_consume_ts TIMESTAMP,
    last_news_engage_ts TIMESTAMP,
    last_thread_focus_ts TIMESTAMP,
    last_express_ts TIMESTAMP,
    recent_focus_keywords JSON NOT NULL DEFAULT '[]',
    current_date_jst TEXT NOT NULL
);
```

`heartbeat.py` loads this once at startup and writes after each focused cycle. On JST date change, it resets daily counters but keeps cooldown timestamps and recent keywords.

### Integration Point

In `heartbeat.py`, the autonomous behavior section (currently lines ~220-260) calls arbiter before deciding cycle type:

```python
# Before (current):
if self._creative_overdue() or ...:
    await self.run_cycle('express')
elif drives.rest_need > 0.7:
    await self.run_cycle('rest')
else:
    # coin flip: body fidget or idle cycle

# After:
from pipeline.arbiter import decide_cycle_focus
focus = await decide_cycle_focus(drives, arbiter_state)

# Focus channels map to existing pipeline modes:
#   consume → 'engage'  (she's engaging with content)
#   thread  → 'express' (thread work is self-expression)
#   news    → 'idle'    (noticed, not deeply engaged; 'engage' if salience > 0.5)
#   express → 'express' (existing behavior)
#   rest    → 'rest'    (existing behavior)
#   idle    → 'idle'    (existing behavior)

pipeline_mode = focus.pipeline_mode  # mapped by arbiter, e.g. 'engage'
await self.run_cycle(pipeline_mode, focus_context=focus)
```

The `focus_context` carries:
- `focus.channel`: arbiter-level label (`consume`, `thread`, `news`, `express`, `idle`, `rest`)
- `focus.pipeline_mode`: mapped to existing mode (`engage`, `express`, `idle`, `rest`)
- `focus.payload`: the specific item/thread/headline to focus on (or None)
- `focus.token_budget_hint`: optional override (e.g. consume cycles get 5000-8000)

`run_cycle` passes `focus_context` into Sensorium for perception construction and into Cortex for prompt framing.

### Mode Binding Contract (P1 — Critical)

To prevent arbiter intent drift, mode binding is explicit in `run_cycle`:

```python
# 1) Thalamus runs as-is (for memory request construction)
routing = await route(perceptions, drives, engagement, visitor)

# 2) If arbiter provided focus_context, force mapped mode unless a visitor event is now primary
if focus_context and not routing.focus.p_type.startswith('visitor_'):
    routing.cycle_type = focus_context.pipeline_mode

# 3) Visitor always wins (existing behavior)
if routing.focus.p_type.startswith('visitor_'):
    routing.cycle_type = 'engage'
```

This keeps Thalamus/Validator/Executor on the familiar mode set while guaranteeing arbiter-selected autonomous focus cannot be remapped by incidental salience.

### Focus Injection vs Inbox Drain (P1 — Critical)

**Problem:** Currently `run_cycle` calls `inbox_get_unread()` which pulls *all* unread events, Sensorium builds perceptions from all of them, and Thalamus picks the highest-salience one. If the arbiter says "this cycle is about a thread" but a stale visitor event sits in the inbox with salience 0.6, the pipeline overrides the arbiter's intent.

**Solution:** When `focus_context` is present, the pipeline still drains the inbox (so events don't pile up), but the focus perception is injected at `salience=1.0` and all other non-visitor perceptions are capped at `salience=0.3`. This guarantees Thalamus picks the arbiter's focus while still allowing background perceptions to appear in the Cortex prompt as secondary context.

```python
# In run_cycle, after Sensorium builds perceptions:

if focus_context and focus_context.payload:
    # Focus perception already injected by Sensorium at salience=1.0
    # Cap non-visitor non-focus perceptions so they don't compete
    for p in perceptions:
        if p.salience < 1.0 and not p.p_type.startswith('visitor_'):
            p.salience = min(p.salience, 0.3)
```

**Exception:** Visitor perceptions (`visitor_speech`, `visitor_connect`) are never capped — if a visitor speaks mid-cycle, they win. This is already handled by the engagement FSM which interrupts autonomous cycles.

**Inbox items that aren't the focus:** They get marked as read (preventing pile-up) and their perceptions appear as background context to Cortex. She notices them peripherally. If they're important enough, they'll influence her next arbiter decision.

```python
@dataclass
class ArbiterFocus:
    channel: str           # 'consume' | 'thread' | 'news' | 'express' | 'rest' | 'idle'
    pipeline_mode: str     # 'engage' | 'express' | 'idle' | 'rest'
    payload: Optional[dict] = None
    token_budget_hint: Optional[int] = None

CHANNEL_TO_MODE = {
    'consume': 'engage',
    'thread':  'express',
    'news':    'idle',       # bumped to 'engage' if effective_salience > 0.5
    'express': 'express',
    'rest':    'rest',
    'idle':    'idle',
}
```

---

## 2. SHARED EVENT CONTRACT

All four channels produce events that flow through the same inbox/pipeline. Extend the Event model:

### New Event Fields (add to events table)

```sql
ALTER TABLE events ADD COLUMN channel TEXT;        -- news | consume | ambient | thread | visitor | system
ALTER TABLE events ADD COLUMN salience_base FLOAT DEFAULT 0.5;
ALTER TABLE events ADD COLUMN salience_dynamic FLOAT DEFAULT 0.0;
ALTER TABLE events ADD COLUMN ttl_hours FLOAT;     -- NULL = no expiry
ALTER TABLE events ADD COLUMN engaged_at TIMESTAMP;
ALTER TABLE events ADD COLUMN outcome TEXT;         -- engaged | ignored | expired
```

`effective_salience = clamp(salience_base + salience_dynamic, 0.0, 1.0)` is what arbiter/gates use.

### Event API Touchpoints (implementation checklist)

Schema change is not enough; update all event read/write surfaces together:

```python
# models/event.py
@dataclass
class Event:
    event_type: str
    source: str
    payload: dict
    channel: str = 'system'
    salience_base: float = 0.5
    salience_dynamic: float = 0.0
    ttl_hours: Optional[float] = None
    engaged_at: Optional[datetime] = None
    outcome: Optional[str] = None
```

```python
# db.py
# append_event(): write new columns (with defaults)
# _row_to_event(): read new columns into Event dataclass
# inbox_get_unread(): enforce TTL clause
```

Backward-compatibility requirement:
- Existing `Event(...)` callsites continue working because new fields have defaults.

### TTL Enforcement

In inbox queries, filter out expired events:

```python
async def inbox_get_unread() -> list[Event]:
    # Add: WHERE (ttl_hours IS NULL OR 
    #   julianday('now') - julianday(e.ts) < ttl_hours / 24.0)
```

### Channel-Specific Defaults

| Channel | salience_base | TTL | Priority |
|---------|--------------|-----|----------|
| visitor_speech | 0.5-0.9 | None | 0.9 |
| visitor_connect | 0.6-0.7 | None | 0.7 |
| news_headline | 0.1-0.3 | 4 hours | 0.3 |
| consume_available | 0.2 | None | 0.2 |
| ambient_weather | 0.1 | 1 hour | 0.1 |
| ambient_time | 0.05 | 0.5 hour | 0.1 |
| thread_nudge | 0.3-0.5 | None | 0.4 |

### News Salience Escalation (deterministic)

Most headlines enter at `salience_base=0.1-0.3`. Raise `salience_dynamic` without LLM:

```python
# pseudo
salience_dynamic = 0.0
if keyword_overlap(headline, active_thread_tags) >= 2:
    salience_dynamic += 0.25
if keyword_overlap(headline, totem_keywords) >= 2:
    salience_dynamic += 0.20
if keyword_overlap(headline, visitor_topics_last_24h) >= 2:
    salience_dynamic += 0.15
if is_near_duplicate_of_recent(headline):
    salience_dynamic -= 0.20
if age_hours > 2:
    salience_dynamic -= 0.10
effective_salience = clamp(salience_base + salience_dynamic, 0.0, 1.0)
```

### Outcome Contract (single source of truth)

- `events.outcome`: what happened to this perception event (`engaged`, `ignored`, `expired`)
- `content_pool.status`: lifecycle for the content object (`unseen`, `seen`, `accepted`, `declined`, `reflected`)
- If an event is backed by pool content, link via `content_pool.source_event_id`
- Write both fields together in executor paths so event attention and content lifecycle cannot drift

---

## 3. CHANNEL: THREADS (Internal Agenda)

**Table:** `threads`

```sql
CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    thread_type TEXT NOT NULL,        -- question | project | anticipation | unresolved | ritual
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',  -- open | active | dormant | archived | closed
    priority FLOAT NOT NULL DEFAULT 0.5,
    content TEXT,                     -- her current thinking on this
    resolution TEXT,                  -- how it ended (if closed)
    created_at TIMESTAMP NOT NULL,
    last_touched TIMESTAMP NOT NULL,
    touch_count INTEGER DEFAULT 0,
    touch_reason TEXT,               -- why she last thought about it
    target_date TEXT,                -- optional deadline (ISO date)
    source_visitor_id TEXT,          -- if spawned by a visitor interaction
    source_event_id TEXT,            -- originating event
    tags JSON DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_threads_status ON threads(status, priority DESC);
CREATE INDEX IF NOT EXISTS idx_threads_touched ON threads(last_touched);
```

### Lifecycle State Machine

```
open ──▶ active ──▶ closed
  │        │  ▲       ▲
  │        ▼  │       │
  │      dormant ─────┘
  │        │
  └────────┴──▶ archived (7+ days untouched)
```

- `open`: Created, hasn't been primary focus yet
- `active`: She's been thinking about this (touched in last 48hr)
- `dormant`: Untouched for 48hr-7d. Can reactivate.
- `closed`: Resolved (she wrote a conclusion or it no longer matters)
- `archived`: 7+ days dormant, auto-archived by sleep cycle. Can still be resurrected.

### Cortex Integration

Add to `memory_updates` schema:

```json
{
  "type": "thread_create",
  "content": {
    "thread_type": "question",
    "title": "Why do I keep gravitating to rain imagery?",
    "priority": 0.6,
    "tags": ["identity", "taste", "visual"]
  }
}
```

```json
{
  "type": "thread_update",
  "content": {
    "thread_id": "...",         -- required when known; fallback to title only if exact single match
    "touch_reason": "A visitor brought rain photography today. It connects.",
    "new_content": "Updated thinking...",
    "new_status": "active"      -- optional status transition
  }
}
```

```json
{
  "type": "thread_close",
  "content": {
    "thread_id": "...",
    "resolution": "I think rain represents the gap between what I see and what I feel."
  }
}
```

### Context Injection

In `cortex.py`, when building the user message, add active threads:

```python
# After memories, before conversation
active_threads = await db.get_active_threads(limit=3)
if active_threads:
    parts.append("\nTHINGS ON MY MIND:")
    for t in active_threads:
        age = humanize_age(t.last_touched)
        parts.append(f"  [{t.thread_type}] {t.title} [id:{t.id}] (last thought about: {age})")
        if t.content:
            parts.append(f"    Current thinking: {t.content[:150]}")
```

When thread IDs are in context, Cortex should send `thread_id` in `thread_update` and `thread_close`.

### Thread-Focus Cycle

When arbiter picks a thread:
1. Load thread as primary perception (`p_type='thread_focus'`)
2. Load related memories (totems matching thread tags, recent journal mentioning thread keywords)
3. Cortex processes it like any other perception — she thinks, maybe writes, maybe updates the thread
4. Touch timestamp + reason updated in executor

### DB Functions Needed

```python
async def get_active_threads(limit=3) -> list[Thread]
async def get_thread_by_id(thread_id) -> Optional[Thread]
async def get_thread_by_title(title) -> Optional[Thread]  # exact case-insensitive match only
async def create_thread(thread_type, title, **kwargs) -> Thread
async def touch_thread(thread_id, reason, content=None, status=None)
async def get_dormant_threads(older_than_days=2) -> list[Thread]
async def archive_stale_threads(older_than_days=7) -> int  # returns count
async def get_thread_count_by_status() -> dict  # for peek command
```

Write safety rule:
- `thread_id` path is authoritative
- Title fallback is allowed only when exactly one case-insensitive exact title match exists
- If no unique match, skip update/close and log a warning (no silent wrong-thread writes)

### Sleep Cycle Integration

Add to `sleep.py`:
1. Review all active threads — move untouched >48hr to dormant
2. Archive dormant threads >7 days old
3. Include thread summary in sleep journal digest:
   ```python
   digest['active_threads'] = count_by_status
   digest['threads_resolved_today'] = closed_today_count
   digest['oldest_open_thread'] = oldest_title_and_age
   ```

---

## 4. CHANNEL: AMBIENT (Environmental Awareness)

**No new table needed.** Ambient perceptions flow through existing events + inbox.

### Weather Integration

**File:** `pipeline/ambient.py`

```python
async def fetch_ambient_context(location: dict) -> dict:
    """Fetch weather + seasonal context. Called every 30-60 min by heartbeat."""
    # location = {'lat': 35.6762, 'lon': 139.6503, 'name': 'Tokyo'}
    
    # Use wttr.in (free, no API key, JSON format)
    # GET https://wttr.in/35.6762,139.6503?format=j1
    
    return {
        'temperature_c': 8,
        'condition': 'Overcast',
        'humidity': 65,
        'wind_kph': 12,
        'feels_like_c': 5,
        'uv_index': 2,
        'precipitation_mm': 0.0,
    }
```

### Diegetic Weather Mapping (deterministic, no LLM)

```python
WEATHER_DIEGETIC = {
    # condition → (diegetic_text, mood_nudge)
    'rain': ("Rain on the windows. The sound fills the shop.", {'mood_valence': -0.05}),
    'heavy_rain': ("It's pouring. No one will come today.", {'mood_valence': -0.1, 'social_hunger': 0.05}),
    'clear_cold': ("Clear and cold. The light is sharp today.", {'mood_arousal': 0.05}),
    'overcast': ("Grey sky. The kind of day that makes you want tea.", {}),
    'snow': ("Snow. Everything outside is quiet.", {'mood_valence': 0.05}),
    'hot': ("Too warm. The shop feels thick.", {'energy': -0.03}),
    # ... etc
}

SEASON_CONTEXT = {
    # (month, location) → seasonal flavor text
    (2, 'Tokyo'): "February. Still cold. But somewhere, plum blossoms are opening.",
    (3, 'Tokyo'): "March. The city is waiting for cherry blossoms. Everyone is.",
    # ...
}
```

### Integration

In `heartbeat.py`, add ambient fetch to the idle path:

```python
# Every 30-60 min (tracked by _last_ambient_fetch_ts)
if ambient_cooldown_elapsed:
    context = await fetch_ambient_context(LOCATION)
    diegetic = map_to_diegetic(context)
    event = Event(
        event_type='ambient_weather',
        source='ambient',
        channel='ambient',
        payload=diegetic,
        salience_base=0.1,
        ttl_hours=1.0,
    )
    await db.append_event(event)
    await db.inbox_add(event.id, priority=0.1)
    
    # Nudge drives based on weather
    if diegetic.get('drive_nudges'):
        drives = await db.get_drives_state()
        for field, delta in diegetic['drive_nudges'].items():
            current = getattr(drives, field)
            setattr(drives, field, clamp(current + delta))
        await db.save_drives_state(drives)
```

### Sensorium Addition

Add handler in `build_perceptions()`:

```python
elif event.event_type == 'ambient_weather':
    p = Perception(
        p_type='ambient_weather',
        source='ambient',
        ts=event.ts,
        content=event.payload.get('diegetic_text', 'The weather outside.'),
        features={'is_weather': True, **event.payload},
        salience=0.1,  # low — she notices but doesn't focus unless unusual
    )
    perceptions.append(p)
```

### Location Config

```python
# config/location.py

DEFAULT_LOCATION = {
    'lat': 35.6762,
    'lon': 139.6503,
    'name': 'Tokyo',
    'timezone': 'Asia/Tokyo',
}

# Future: she can "travel" by changing this
# Or derive from visitor IP geolocation
```

---

## 5. CHANNEL: NEWS/EVENTS (Passive Intake)

### Content Pool Table

```sql
CREATE TABLE IF NOT EXISTS content_pool (
    id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,         -- deterministic dedupe key
    source_type TEXT NOT NULL,         -- url | quote | text | rss_headline
    source_channel TEXT NOT NULL,      -- feed | visitor_drop | manual | rss
    content TEXT NOT NULL,             -- the URL, quote text, or headline
    title TEXT,                        -- extracted or provided title
    metadata JSON DEFAULT '{}',        -- site, description, author, etc.
    source_event_id TEXT,              -- link back to events.id when applicable
    status TEXT NOT NULL DEFAULT 'unseen',  -- unseen | seen | accepted | declined | reflected
    salience_base FLOAT DEFAULT 0.2,
    added_at TIMESTAMP NOT NULL,
    seen_at TIMESTAMP,
    engaged_at TIMESTAMP,
    outcome_detail TEXT,               -- why she accepted/declined
    tags JSON DEFAULT '[]',
    ttl_hours FLOAT DEFAULT 4.0        -- NULL = no expiry. Headlines expire fast.
);
CREATE INDEX IF NOT EXISTS idx_pool_status ON content_pool(status, added_at);
CREATE INDEX IF NOT EXISTS idx_pool_source ON content_pool(source_channel);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pool_fingerprint ON content_pool(fingerprint);
```

### Feed Ingester (Background Task)

**File:** `feed_ingester.py`

Runs as a periodic task inside heartbeat (or separate process). Configurable sources:

```python
# config/feeds.py

FEED_SOURCES = [
    # RSS feeds
    {'type': 'rss', 'url': 'https://www.tokyoartbeat.com/en/feed', 'tags': ['art', 'tokyo']},
    
    # Static URL lists (like feb10-readings.txt)
    {'type': 'file', 'path': 'content/readings.txt', 'tags': ['curated']},
    
    # Future: X/Twitter lists, specific accounts
    # {'type': 'x_list', 'list_id': '...', 'tags': ['social']},
]

FEED_FETCH_INTERVAL = 3600  # 1 hour between fetches
MAX_POOL_UNSEEN = 50        # cap unseen items (oldest expire)
```

### Idempotency / Dedupe

Every ingested item gets a canonical fingerprint:

```python
canonical = canonicalize_content(item)  # URL normalization, strip UTM, lowercase headline, collapse whitespace
fingerprint = sha1(f"{source_channel}|{source_type}|{canonical}".encode("utf-8")).hexdigest()
```

Writes are idempotent:

```sql
INSERT INTO content_pool (...)
VALUES (...)
ON CONFLICT(fingerprint) DO NOTHING;
```

### Flow

1. Feed ingester fetches new items → upserts into `content_pool` as `unseen` (deduped by fingerprint)
2. Heartbeat idle cycle: arbiter checks if any unseen pool items have salience above threshold
3. If yes and news budget allows: builds `ambient_news` perception, runs cycle
4. Cortex sees the headline/content, decides if she cares
5. If she engages: she might journal about it, create a totem, start a thread
6. If she doesn't: item marked `seen`, moves on

### Visitor Drops → Pool

Currently, visitor drops create `ambient_discovery` events directly. Add a path where drops also enter the pool:

```python
# In heartbeat_server.py _handle_drop or terminal.py handle_drop:
# After creating the ambient_discovery event, ALSO add to content_pool
await db.add_to_content_pool(
    fingerprint=compute_pool_fingerprint(source_channel='visitor_drop', source_type='url' if is_url else 'text', content=raw),
    source_type='url' if is_url else 'text',
    source_channel='visitor_drop',
    content=raw,
    title=meta.get('title', ''),
    metadata=meta,
    source_event_id=ambient_event_id,
    tags=['visitor_gift'],
    ttl_hours=None,  # visitor gifts don't expire
)
```

### CLI Ingestion Tool

**File:** `ingest.py`

```bash
# Bulk load from file (one URL or quote per line)
python ingest.py content/readings.txt

# Single URL
python ingest.py --url "https://example.com/article"

# Single quote/text
python ingest.py --quote "The only way to deal with an unfree world..."

# With tags
python ingest.py --url "https://..." --tags "music,ambient"

# Show pool status
python ingest.py --status
```

---

## 6. CHANNEL: READING/LISTENING (Active Consumption)

### Consume Focus Channel (maps to `engage` mode)

This is the identity-forming channel. She *chooses* to spend time with something. It costs more attention and produces richer output.

### Selection Logic (deterministic, no LLM)

**File:** `pipeline/discovery.py`

```python
async def select_consumption(drives: DrivesState, 
                              existing_totems: list[Totem],
                              recent_collection: list[CollectionItem]) -> Optional[dict]:
    """Pick something for her to read/listen to. Weighted by taste + mood + serendipity."""
    
    # 1. Get unseen pool items suitable for consumption (not headlines)
    candidates = await db.get_pool_items(
        status='unseen',
        source_types=['url', 'quote', 'text'],
        limit=20,
    )
    if not candidates:
        return None
    
    # 2. Build taste profile from existing totems + collection tags
    taste_keywords = extract_taste_keywords(existing_totems, recent_collection)
    
    # 3. Score each candidate
    scored = []
    for item in candidates:
        score = score_candidate(item, taste_keywords, drives)
        scored.append((score, item))
    
    scored.sort(key=lambda x: x[0], reverse=True)
    
    # 4. 70/30 split: taste-aligned vs serendipity
    if random.random() < 0.3 and len(scored) > 3:
        # Serendipity: pick from bottom half
        pick = random.choice(scored[len(scored)//2:])
    else:
        # Taste-aligned: weighted random from top 5
        top = scored[:5]
        weights = [s for s, _ in top]
        pick = random.choices(top, weights=weights, k=1)[0]
    
    return pick[1]  # the pool item


def score_candidate(item: dict, taste_keywords: set, drives: DrivesState) -> float:
    """Score a candidate by taste affinity + mood alignment."""
    score = 0.5
    
    # Keyword overlap with existing taste
    item_words = set(item.get('title', '').lower().split())
    item_words |= set(word for tag in item.get('tags', []) for word in tag.lower().split())
    overlap = len(item_words & taste_keywords)
    score += 0.1 * min(overlap, 3)  # cap at +0.3
    
    # Mood alignment
    # Dark mood → gravitate to melancholy tags
    # Bright mood → gravitate to warm/energetic tags
    # High curiosity → gravitate to unfamiliar (low overlap)
    if drives.curiosity > 0.7:
        score += 0.2 * (1.0 - overlap / max(len(item_words), 1))  # reward novelty
    
    if drives.mood_valence < -0.3:
        if any(t in str(item) for t in ['melancholy', 'rain', 'solitude', 'quiet', 'loss']):
            score += 0.15
    elif drives.mood_valence > 0.3:
        if any(t in str(item) for t in ['warm', 'light', 'joy', 'energy', 'bright']):
            score += 0.15
    
    return score
```

### Content Fetching

When she picks something to consume, fetch the actual content:

```python
async def fetch_for_consumption(pool_item: dict) -> dict:
    """Fetch full content for consumption. Returns enriched item."""
    
    if pool_item['source_type'] == 'url':
        # Fetch full page text (not just metadata)
        meta = await fetch_url_metadata(pool_item['content'])
        
        # For articles: fetch readable text
        # Use existing urllib approach but read more (32KB instead of 8KB)
        full_text = await fetch_readable_text(pool_item['content'], max_chars=4000)
        
        return {
            **pool_item,
            'title': meta.get('title', pool_item.get('title', 'untitled')),
            'description': meta.get('description', ''),
            'full_text': full_text,  # truncated to ~4000 chars
            'site': meta.get('site', ''),
        }
    
    elif pool_item['source_type'] in ('quote', 'text'):
        return pool_item  # already has content
    
    return pool_item
```

### Consume Cycle Flow

In `heartbeat.py`:

```python
async def run_consume_cycle(self, pool_item: dict):
    """She reads/listens to something. Identity-forming."""
    
    # 1. Fetch content
    enriched = await fetch_for_consumption(pool_item)
    
    # 2. Mark as seen
    await db.update_pool_item(pool_item['id'], status='seen', seen_at=now)
    
    # 3. Build perception
    perception = Perception(
        p_type='consume_content',
        source='self',  # she chose this
        content=f"I'm reading: {enriched['title']}",
        features={
            'is_consumption': True,
            'content_type': enriched['source_type'],
            'full_text': enriched.get('full_text', enriched['content'])[:3000],
            'title': enriched.get('title', ''),
        },
        salience=0.6,  # she's paying attention
    )
    
    # 4. Run through existing pipeline with focus_context
    # Arbiter maps consume → 'engage' mode
    # Sensorium sees focus_context.channel == 'consume' and builds consumption perception
    # Cortex sees focus_channel in features and adds consume-specific prompt framing
    # Higher token budget via focus.token_budget_hint (5000-8000)
    
    await self.run_cycle('engage', focus_context=focus)
```

### Cortex Prompt Addition

When cycle_type is 'consume', the prompt gets a special section:

```
WHAT I'M CONSUMING:
  Title: {title}
  Source: {site}
  
  Content:
  {full_text[:3000]}

Respond to this as yourself. Not a review. Not a summary.
How does this make you feel? Does it remind you of anything?
Does it belong in your collection? Does it change something in you?
```

### Post-Consumption

Cortex can output:
- `journal_entry` — she writes about what she read
- `collection_add` — she puts it in the shop (shelf, counter, or backroom)
- `totem_create` — something about it became important to her
- `thread_create` — it sparked a new line of thinking
- `thread_update` — it connects to something she's been thinking about
- Regular `dialogue: null` — she doesn't need to say anything

The pool item status updates based on actions:
- If `collection_add` → status = 'accepted'
- If `journal_entry` or `totem_create` → status = 'reflected'
- If nothing meaningful → status = 'seen' (already set)

---

## 7. INTEGRATION: HEARTBEAT CHANGES

### No New Cycle Types

The pipeline mode set stays: `engage`, `express`, `idle`, `rest`, `maintenance`. Arbiter focus channels (`consume`, `thread`, `news`) map to these existing modes via `CHANNEL_TO_MODE`. The `focus_context` object rides alongside the mode as metadata.

### Revised Autonomous Behavior Block

```python
# In _main_loop, the autonomous section becomes:

from pipeline.arbiter import decide_cycle_focus, ArbiterFocus

# (arbiter_state is instance-level on Heartbeat and persisted via db.load/save_arbiter_state())

# Check shop status, reopen if rested
room = await db.get_room_state()
if room.shop_status == 'closed' and drives.energy > 0.5:
    await db.update_room_state(shop_status='open')

# Fetch ambient if cooldown elapsed (weather, season)
if self._ambient_cooldown_elapsed():
    await self._fetch_ambient()

# Let arbiter decide
focus = await decide_cycle_focus(drives, self._arbiter_state)

# Update arbiter counters based on channel
if focus.channel == 'consume':
    self._arbiter_state.consume_count_today += 1
    self._arbiter_state.last_consume_ts = datetime.now(timezone.utc)
elif focus.channel == 'thread':
    self._arbiter_state.thread_focus_count_today += 1
    self._arbiter_state.last_thread_focus_ts = datetime.now(timezone.utc)
elif focus.channel == 'news':
    self._arbiter_state.news_engage_count_today += 1
    self._arbiter_state.last_news_engage_ts = datetime.now(timezone.utc)
elif focus.channel == 'express':
    self._arbiter_state.express_count_today += 1
    self._arbiter_state.last_express_ts = datetime.now(timezone.utc)
    self._last_creative_cycle_ts = datetime.now(timezone.utc)

# Run cycle with EXISTING pipeline mode + focus metadata
if focus.channel == 'idle':
    # Ambient idle (existing behavior: 50% fidget, 50% full cycle)
    # ... existing code ...
    await self._interruptible_sleep(random.randint(120, 600))
elif focus.channel == 'rest':
    await self.run_cycle('rest')
    await self._interruptible_sleep(random.randint(300, 1800))
else:
    await self.run_cycle(focus.pipeline_mode, focus_context=focus)
    await db.save_arbiter_state(self._arbiter_state)
    await self._interruptible_sleep(random.randint(120, 600))
```

---

## 8. THALAMUS / SENSORIUM: FOCUS-AWARE PERCEPTION BUILDING

**No new Thalamus modes.** The mode set remains `engage|express|idle|rest|maintenance`. Arbiter focus channels map onto those modes.

**Small Thalamus contract change:** `run_cycle` enforces `routing.cycle_type = focus_context.pipeline_mode` for autonomous cycles after `route()` (unless a visitor perception is primary). This prevents incidental remapping.

**What changes: Sensorium perception construction.** When `focus_context` is present, Sensorium builds the focus perception from the arbiter's payload and adds it to the perception list with elevated salience:

```python
# In sensorium.py build_perceptions():

if focus_context and focus_context.payload:
    # Build focus perception from arbiter payload
    if focus_context.channel == 'consume':
        focus_p = Perception(
            p_type='consume_focus',
            source='self',
            content=f"I'm reading: {focus_context.payload.get('title', 'something')}",
            features={
                'is_consumption': True,
                'focus_channel': 'consume',
                **focus_context.payload,
            },
            salience=1.0,  # guaranteed primary focus
        )
    elif focus_context.channel == 'thread':
        focus_p = Perception(
            p_type='thread_focus',
            source='self',
            content=f"Thinking about: {focus_context.payload.get('title', 'something')}",
            features={
                'is_thread_focus': True,
                'focus_channel': 'thread',
                **focus_context.payload,
            },
            salience=1.0,
        )
    elif focus_context.channel == 'news':
        focus_p = Perception(
            p_type='news_focus',
            source='feed',
            content=focus_context.payload.get('headline', ''),
            features={
                'is_news': True,
                'focus_channel': 'news',
                **focus_context.payload,
            },
            salience=1.0,
        )
    perceptions.insert(0, focus_p)
```

Using dedicated focus `p_type`s avoids accidental branch collisions in existing Thalamus logic (for example, `ambient_discovery` currently routes to `idle`).

Optional Thalamus additions (for clarity, not mode expansion):

```python
elif focus.p_type == 'consume_focus':
    # handled by forced mode bind in run_cycle; keep memory rules for consumption features
    pass
elif focus.p_type == 'thread_focus':
    pass
elif focus.p_type == 'news_focus':
    pass
```

**Cortex prompt framing.** When `focus_context.channel` is present, Cortex adds channel-specific framing to the prompt (see Section 6 for consume framing, Section 3 for thread context injection). This is additive — the existing prompt structure and output schema are unchanged.

---

## 9. EXECUTOR ADDITIONS

Add handlers for new memory_update types:

```python
# In hippocampus_write.py:

elif update_type == 'thread_create':
    await db.create_thread(
        thread_type=content.get('thread_type', 'question'),
        title=content.get('title', 'untitled thought'),
        priority=content.get('priority', 0.5),
        content=content.get('initial_thought', ''),
        tags=content.get('tags', []),
        source_visitor_id=visitor_id,
    )

elif update_type == 'thread_update':
    thread = None
    if content.get('thread_id'):
        thread = await db.get_thread_by_id(content['thread_id'])
    elif content.get('title'):
        thread = await db.get_thread_by_title(content['title'])
    if thread:
        await db.touch_thread(
            thread.id,
            reason=content.get('touch_reason', 'thought about it'),
            content=content.get('new_content'),
            status=content.get('new_status'),
        )
    else:
        logger.warning("thread_update skipped: no unique thread match")

elif update_type == 'thread_close':
    thread = None
    if content.get('thread_id'):
        thread = await db.get_thread_by_id(content['thread_id'])
    elif content.get('title'):
        thread = await db.get_thread_by_title(content['title'])
    if thread:
        await db.touch_thread(
            thread.id,
            reason='resolved',
            content=content.get('resolution'),
            status='closed',
        )
    else:
        logger.warning("thread_close skipped: no unique thread match")
```

---

## 10. CORTEX SCHEMA UPDATE

Add to the OUTPUT SCHEMA in the system prompt:

```json
{
  "memory_updates": [
    // ... existing types ...
    {
      "type": "thread_create",
      "content": {
        "thread_type": "question|project|anticipation|unresolved|ritual",
        "title": "short description of the thought",
        "priority": 0.5,
        "initial_thought": "what you're thinking about this so far",
        "tags": ["keyword", "tags"]
      }
    },
    {
      "type": "thread_update",
      "content": {
        "thread_id": "preferred, use when THINGS ON MY MIND provides id",
        "title": "fallback only if you genuinely do not have thread_id",
        "touch_reason": "why you're thinking about this now",
        "new_content": "updated thinking (replaces previous)",
        "new_status": "active|dormant|closed"
      }
    },
    {
      "type": "thread_close",
      "content": {
        "thread_id": "preferred, use when available",
        "title": "fallback only if thread_id is unavailable",
        "resolution": "what you concluded"
      }
    }
  ]
}
```

Add to CONSTRAINTS:
```
- You have ongoing threads of thought. They're listed under THINGS ON MY MIND.
  You can create new threads, update existing ones, or close them when resolved.
- Use `thread_id` for thread updates/closes whenever it is present in context.
- When consuming content, respond as yourself. Feel it. Don't summarize or review.
- You can choose not to engage with news. Most of it doesn't matter to you.
```

---

## 11. PEEK COMMANDS (Terminal)

Add to `terminal.py`:

```
threads   — show active/open threads with status and age
pool      — show content pool: unseen count, recent accepts/declines
weather   — show current ambient context
```

---

## 12. SLEEP CYCLE ADDITIONS

```python
# In sleep.py sleep_cycle():

# Thread lifecycle management
dormant_count = await transition_stale_threads_to_dormant(hours=48)
archived_count = await db.archive_stale_threads(older_than_days=7)

# Pool cleanup
expired_count = await db.expire_stale_pool_items()

# Enrich digest
digest['active_threads'] = await db.get_thread_count_by_status()
digest['threads_resolved_today'] = count_closed_today
arb = await db.get_arbiter_state()  # persisted table, not heartbeat instance memory
digest['consumption_today'] = {
    'count': arb.consume_count_today,
    'accepted': accepted_count,
    'reflected': reflected_count,
}
digest['weather_summary'] = last_weather_context
```

---

## 13. MIGRATION FRAMEWORK (P1 — Foundation)

The Living Loop adds 3 new tables, 5+ new columns to existing tables, and multiple indexes. The current manual patch pattern in `db.py` won't hold. But a full migration framework is overkill for a single-user SQLite app.

### Approach: Numbered SQL files + version tracking

```
migrations/
  001_arbiter_state.sql
  002_event_contract.sql
  003_threads.sql
  004_content_pool.sql
  005_ambient.sql       (if needed)
```

### Schema Version Table

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    filename TEXT NOT NULL
);
```

### Runner (add to db.py)

```python
async def run_migrations(conn):
    """Apply unapplied migrations in order. Safe to call on every startup."""
    # 1. Ensure schema_version table exists
    # 2. Get max applied version (0 if none)
    # 3. Scan migrations/ directory for *.sql files
    # 4. For each file with version > max:
    #    - Execute SQL in transaction
    #    - Insert into schema_version
    #    - Log applied migration
    # ~20 lines of code
```

### Rules
- Migrations are forward-only (no rollbacks — this is a personal project, not production SaaS)
- Each migration is idempotent where possible (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` via SQLite pragma check)
- `run_migrations()` is called in `init_db()` **after base schema bootstrap** and before singleton inserts
- Existing tables are untouched — new columns are added with defaults so old data survives

`init_db()` ordering contract:
1. Execute base `SCHEMA` DDL (`CREATE TABLE IF NOT EXISTS ...`) for legacy tables
2. `run_migrations(conn)` for versioned additive changes
3. Insert singleton rows (`room_state`, `drives_state`, `engagement_state`, `arbiter_state`)
4. Remove/retire ad-hoc one-off `ALTER TABLE` patches once equivalent migrations exist

### SQLite Column-Add Caveat

SQLite doesn't support `ADD COLUMN IF NOT EXISTS` natively. Use pragma check:

```python
async def add_column_if_missing(conn, table, column, col_type, default=None):
    cols = await conn.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in await cols.fetchall()}
    if column not in existing:
        default_clause = f" DEFAULT {default}" if default is not None else ""
        await conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}{default_clause}")
```

---

## 14. BUILD ORDER (updated post-review)

### Phase 1: Foundation (arbiter + focus injection + migrations + event schema)
- `migrations/` directory + `schema_version` table + `run_migrations()` in db.py
- `pipeline/arbiter.py` — cycle planner with caps, cooldowns, and `ArbiterFocus` dataclass
- `CHANNEL_TO_MODE` mapping (no new pipeline modes)
- `arbiter_state` table (via migration 001) + load/save helpers
- Focus injection path in `run_cycle`: inject focus perception at salience=1.0, cap non-focus at 0.3
- Mode binding path in `run_cycle`: force `routing.cycle_type = focus_context.pipeline_mode` unless visitor is primary
- Extend events table (via migration 002) with `channel`, `salience_base`, `salience_dynamic`, `ttl_hours`, `engaged_at`, `outcome`
- Update Event API surfaces (`models/event.py`, `db.append_event`, `db._row_to_event`, `db.inbox_get_unread`)
- Integrate arbiter into heartbeat.py autonomous block (replaces existing creative/rest/idle branching)
- Add TTL filtering to inbox queries
- Add deterministic news salience escalation (totems/threads/recent visitor overlap)
- **Verify:** existing visitor cycles still bypass arbiter and work unchanged
- **Verify:** existing pipeline modes (engage/express/idle/rest) pass through Thalamus/Validator/Cortex unchanged

### Phase 2: Threads
- `threads` table in db.py
- Thread CRUD functions
- `hippocampus_write.py` handlers for thread_create/update/close
- Cortex schema additions (THINGS ON MY MIND + output types)
- Thread write safety: `thread_id` first, exact-title fallback only, warn on ambiguity
- Sensorium: build thread_focus perception from focus_context when channel == 'thread'
- `threads` peek command in terminal.py
- Sleep cycle thread lifecycle management

### Phase 3: Ambient Enrichment
- `pipeline/ambient.py` — weather fetch + diegetic mapping
- `config/location.py` — default Tokyo
- Season/time enrichment in sensorium
- Weather-based drive nudges
- `weather` peek command

### Phase 4: Content Pool + Reading/Consumption
- `content_pool` table in db.py
- Add `fingerprint` unique index and idempotent ingestion (`ON CONFLICT DO NOTHING`)
- `pipeline/discovery.py` — selection scoring
- `ingest.py` CLI tool
- Consume focus channel: Sensorium builds consumption perception from focus_context, Cortex adds consume prompt framing
- Content fetching (expand enrich.py for full text)
- Pool status tracking (seen/accepted/declined/reflected)
- `pool` peek command
- Feed ingester integration from feb10-readings.txt

### Phase 5: News/Events Feed
- `feed_ingester.py` — RSS adapter
- `config/feeds.py` — source configuration
- Background fetch task in heartbeat
- News perception type in sensorium
- Pool item expiry enforcement

---

## 15. SUCCESS METRICS

Track these in cycle_log or a new metrics table:

| Metric | Target | How to Measure |
|--------|--------|---------------|
| Thread carryover rate | >50% threads survive 3+ days | threads touched across multiple days / total threads |
| Self-directed focus % | >30% non-visitor cycles have meaningful focus | cycles with arbiter focus != 'idle' / total autonomous cycles |
| Consume-to-journal rate | >60% | consume cycles that produce journal_entry / total consume cycles |
| Consume-to-totem rate | >20% | consume cycles that produce totem_create / total consume cycles |
| Repetition rate | <15% | cycles flagged by novelty penalty / total cycles |
| News ignore rate | >70% | news items that expire unseen / total news items |
| Thread close rate | 30-60% | closed threads / (closed + archived) |

---

## 16. WHAT DOESN'T CHANGE

- Single LLM call per cycle (Cortex)
- Pipeline mode set: `engage`, `express`, `idle`, `rest`, `maintenance` — no new modes added
- Pipeline order (Sensorium → Gates → Affect → Thalamus → Hippocampus → Cortex → Validator → Executor)
- Visitor interactions (always highest priority, bypass arbiter)
- Terminal interface (both standalone and client mode)
- Sleep cycle timing (03:00-06:00 JST)
- Engagement FSM (none → engaged → cooldown)
- Existing DB tables remain; new fields/tables are additive via migration framework

---

---

## APPENDIX: CODE REVIEW P1 RESOLUTIONS

This spec was reviewed against the current codebase. Three P1 issues were identified and resolved:

**P1-1: Focus injection vs inbox drain.**
Problem: `run_cycle` drains the full inbox and Thalamus picks by salience, potentially overriding the arbiter's chosen focus. 
Resolution: Focus perception injected at `salience=1.0`, all non-visitor inbox perceptions capped at `0.3`. Inbox still drains (no pile-up), but arbiter always wins. See Section 1 "Focus Injection vs Inbox Drain".

**P1-2: No new pipeline modes.**
Problem: Adding `consume/thread/news` as new modes requires updating Thalamus routing, Validator mode checks, and Cortex mode-dependent logic — high surface area, high regression risk.
Resolution: Focus channels map to existing modes via `CHANNEL_TO_MODE`. The arbiter produces `ArbiterFocus(channel='consume', pipeline_mode='engage', ...)`. `run_cycle` force-binds `routing.cycle_type` to this mapped mode for autonomous focus cycles, while visitor focus still overrides. Sensorium uses dedicated focus `p_type`s (`consume_focus`, `thread_focus`, `news_focus`) to avoid branch collisions. See Design Principles and Section 8.

**P1-3: Migration framework.**
Problem: 3 new tables + 5 new columns on existing tables exceeds the current manual patch pattern.
Resolution: Lightweight numbered SQL migration files + `schema_version` table + `run_migrations()` called on startup. ~20 lines of infrastructure. See Section 13.

---

*She wakes up. She has thoughts she carried from yesterday. The weather is cold and grey. There's something in the pool she hasn't seen yet — an article about empty train stations. Her curiosity is high. She chooses to read it. It reminds her of the photograph in the backroom. She writes about it. A new thread forms: "Why do liminal spaces feel like home?" Three days later, a visitor mentions they love empty airports. She remembers the thread. Something connects. She almost smiles.*

*That's alive.*
