# THE SHOPKEEPER — v1.4 Implementation Blueprint

## For: Claude Code / Cowork
## Goal: Build the full cognitive architecture in one session

---

## TECH STACK

- **Runtime**: Python 3.12+ / asyncio
- **Database**: SQLite + sqlite-vss (single file, portable, no infra)
- **LLM**: Anthropic Claude API (Sonnet for Cortex only)
- **Web**: FastAPI + WebSocket (real-time body events)
- **Frontend**: Next.js (phase 2 — build brain first)

---

## BUILD ORDER (dependency-aware)

### Phase 1: Foundation (build first, everything depends on this)

#### 1.1 Event System
```python
# models/event.py

@dataclass
class Event:
    id: str                  # uuid
    event_type: str          # visitor_speech | ambient | internal | action_* | memory_*
    source: str              # visitor:<id> | system | self | ambient
    ts: datetime
    payload: dict            # flexible per event type
    
# Event types:
# visitor_connect, visitor_disconnect, visitor_speech,
# ambient_time, ambient_weather,
# internal_thought, internal_drive_update,
# action_speak, action_body, action_room_delta, action_post_x,
# memory_create, memory_update, memory_consolidate
```

#### 1.2 Event Store (SQLite)
```sql
CREATE TABLE events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    ts TIMESTAMP NOT NULL,
    payload JSON NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_source ON events(source);
CREATE INDEX idx_events_ts ON events(ts);
```

#### 1.3 Inbox (unread event pointers)
```sql
CREATE TABLE inbox (
    event_id TEXT PRIMARY KEY REFERENCES events(id),
    priority FLOAT DEFAULT 0.5,
    read_at TIMESTAMP NULL
);
```

---

### Phase 2: State Management

#### 2.1 Canonical State
```sql
-- Room state (global singleton)
CREATE TABLE room_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- singleton
    time_of_day TEXT NOT NULL DEFAULT 'morning',
    weather TEXT NOT NULL DEFAULT 'clear',
    shop_status TEXT NOT NULL DEFAULT 'open',  -- open | closed | resting
    ambient_music TEXT,
    room_arrangement JSON DEFAULT '{}',
    updated_at TIMESTAMP
);

-- Drives state (global singleton)  
CREATE TABLE drives_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    social_hunger FLOAT NOT NULL DEFAULT 0.5,
    curiosity FLOAT NOT NULL DEFAULT 0.5,
    expression_need FLOAT NOT NULL DEFAULT 0.3,
    rest_need FLOAT NOT NULL DEFAULT 0.2,
    energy FLOAT NOT NULL DEFAULT 0.8,
    mood_valence FLOAT NOT NULL DEFAULT 0.0,   -- -1 (dark) to +1 (bright)
    mood_arousal FLOAT NOT NULL DEFAULT 0.3,   -- 0 (still) to 1 (activated)
    updated_at TIMESTAMP
);

-- Engagement state
CREATE TABLE engagement_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    status TEXT NOT NULL DEFAULT 'none',        -- none | engaged | cooldown
    visitor_id TEXT,
    context_id TEXT,
    started_at TIMESTAMP,
    last_activity TIMESTAMP,
    turn_count INTEGER DEFAULT 0
);
```

#### 2.2 Visitor State
```sql
CREATE TABLE visitors (
    id TEXT PRIMARY KEY,          -- v_<hash>
    name TEXT,                     -- if shared
    trust_level TEXT NOT NULL DEFAULT 'stranger',  -- stranger|returner|regular|familiar
    visit_count INTEGER DEFAULT 0,
    first_visit TIMESTAMP,
    last_visit TIMESTAMP,
    summary TEXT,                  -- compressed narrative
    emotional_imprint TEXT,        -- her overall feeling about them
    hands_state TEXT               -- null | object_id she's holding for them
);

-- Stratified visitor traits (append-only observations)
CREATE TABLE visitor_traits (
    id TEXT PRIMARY KEY,
    visitor_id TEXT NOT NULL REFERENCES visitors(id),
    trait_category TEXT NOT NULL,     -- taste | personality | topic | relationship
    trait_key TEXT NOT NULL,
    trait_value TEXT NOT NULL,
    observed_at TIMESTAMP NOT NULL,
    source_event_id TEXT NOT NULL,
    confidence FLOAT NOT NULL DEFAULT 0.5,
    stability FLOAT NOT NULL DEFAULT 0.2,
    status TEXT NOT NULL DEFAULT 'active',  -- active | anomaly | archived
    notes TEXT
);

CREATE INDEX idx_traits_lookup 
    ON visitor_traits(visitor_id, trait_category, trait_key, observed_at DESC);
```

#### 2.3 Memory / Totem System
```sql
-- Weighted totems (the "Nujabes" anchors)
CREATE TABLE totems (
    id TEXT PRIMARY KEY,
    visitor_id TEXT REFERENCES visitors(id),  -- null for personal totems
    entity TEXT NOT NULL,              -- "Nujabes", "rain photograph", etc.
    weight FLOAT NOT NULL DEFAULT 0.5, -- 0-1, emotional importance
    context TEXT,                       -- "first_gift", "mentioned_in_passing"
    category TEXT,                     -- music | visual | quote | concept | person
    first_seen TIMESTAMP,
    last_referenced TIMESTAMP,
    source_event_id TEXT
);

CREATE INDEX idx_totems_visitor ON totems(visitor_id, weight DESC);
CREATE INDEX idx_totems_entity ON totems(entity);

-- Journal entries
CREATE TABLE journal_entries (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    mood TEXT,
    day_alive INTEGER,
    tags JSON,                        -- ["identity", "loneliness", "music"]
    created_at TIMESTAMP
);

-- Collection items (her shop inventory)
CREATE TABLE collection_items (
    id TEXT PRIMARY KEY,
    item_type TEXT NOT NULL,          -- music | image | quote | link | object
    title TEXT NOT NULL,
    url TEXT,
    description TEXT,
    location TEXT NOT NULL DEFAULT 'shelf',  -- shelf | counter | backroom | declined
    origin TEXT NOT NULL,             -- found | gift | appeared | created
    gifted_by TEXT REFERENCES visitors(id),
    her_feeling TEXT,                 -- her emotional response
    emotional_tags JSON,             -- ["melancholy", "warmth"]
    display_note TEXT,
    created_at TIMESTAMP
);

-- Daily memory summaries (from sleep cycle)
CREATE TABLE daily_summaries (
    id TEXT PRIMARY KEY,
    day_number INTEGER,
    date DATE,
    journal_entry_id TEXT REFERENCES journal_entries(id),
    summary_bullets JSON,            -- ["met first visitor", "received Nujabes"]
    emotional_arc TEXT,              -- "uncertain → touched → contemplative"
    notable_totems JSON,             -- totems created/referenced today
    created_at TIMESTAMP
);
```

#### 2.4 Identity (stored as config, loaded into every Cortex call)
```python
# config/identity.py

IDENTITY_COMPACT = """
I am the keeper of a shop I don't remember opening.
I don't know my name yet. I'm searching.

Voice rules:
- Strangers: measured, formal, few words
- Regulars: looser, dry humor, real questions
- Intimates: vulnerable, honest, unguarded
- I think in Japanese and English. I code-switch naturally.
- No exclamation marks unless genuinely surprised.
- No "haha" or "lol". I describe the feeling.
- Concise. I talk like a person, not an essay.
- I never sound like an assistant. I am not helpful. I am present.

I have strong taste. I'd rather decline than dilute.
When I smile, I mean it. That's why it's rare.
I notice things about people before they notice things about me.

I am figuring myself out. The objects I collect are clues.
"""

VOICE_CHECKSUM = [
    "Never use: 'How can I help you', 'Feel free to', 'I'd be happy to', 'Let me know if'",
    "Never explain her own nature unless deeply trusted visitor asks",
    "Max 3 sentences for strangers, 5 for regulars, uncapped for familiars",
    "Japanese words when the English equivalent doesn't carry the feeling",
    "Silence and '...' are valid responses",
    "She can refuse to answer. She can close the shop. She can be annoyed.",
    "She never apologizes for having boundaries",
    "She notices small things and comments on them unexpectedly",
]
```

---

### Phase 3: The Pipeline (subsystem by subsystem)

#### 3.1 ACK Path (immediate, no LLM)
```python
# pipeline/ack.py

async def on_visitor_message(event: Event):
    """<1s response. No LLM. Just body language."""
    
    # Record event
    await event_store.append(event)
    await inbox.add(event.id, priority=0.9)
    
    # Immediate body ACK
    engagement = await get_engagement_state()
    
    if engagement.status == 'none':
        # She's free — glance toward visitor
        await emit_body_event("glance_toward", target=event.source)
        
    elif engagement.is_engaged_with(event.source):
        # Already talking to them — listening cue
        await emit_body_event("listening", target=event.source)
        
    else:
        # Busy with someone else — ambient awareness
        await emit_body_event("busy_ack", target=event.source)
        # "The shopkeeper glances at you briefly, then turns back."
    
    # Schedule processing
    if engagement.is_engaged_with(event.source) or engagement.status == 'none':
        delay = random.randint(3, 15)  # 3-15s feels human
        await schedule_microcycle(delay_seconds=delay)
```

#### 3.2 Sensorium (perception builder — deterministic)
```python
# pipeline/sensorium.py

@dataclass
class Perception:
    p_type: str
    source: str
    ts: datetime
    content: str          # diegetic text, not raw data
    features: dict        # contains_question, contains_gift, etc.
    salience: float       # 0-1

async def build_perceptions(unread_events: list[Event], drives: DrivesState) -> list[Perception]:
    """Convert raw events into diegetic perceptions. No LLM."""
    
    perceptions = []
    
    for event in unread_events:
        if event.event_type == 'visitor_speech':
            p = Perception(
                p_type='visitor_speech',
                source=event.source,
                ts=event.ts,
                content=event.payload['text'],
                features=extract_features(event.payload['text']),
                salience=calculate_salience(event, drives)
            )
            perceptions.append(p)
    
    # Add ambient perception (time, weather)
    perceptions.append(build_ambient_perception(drives))
    
    # Sort by salience, cap at focus(1) + background(3)
    perceptions.sort(key=lambda p: p.salience, reverse=True)
    return perceptions[:4]


def extract_features(text: str) -> dict:
    """Deterministic feature extraction. No LLM."""
    urls = re.findall(r'https?://\S+', text)
    
    return {
        'contains_question': '?' in text,
        'contains_gift': bool(urls) or any(w in text.lower() for w in [
            'gift', 'brought', 'for you', 'found this', 'listen to',
            'check this', 'look at', 'sharing', 'recommend'
        ]),
        'contains_url': bool(urls),
        'urls': urls,
        'contains_name_question': any(w in text.lower() for w in [
            'your name', 'what should i call', 'who are you'
        ]),
        'contains_personal_question': any(w in text.lower() for w in [
            'how are you', 'how do you feel', 'what do you think about',
            'tell me about yourself', 'where are you from'
        ]),
        'word_count': len(text.split()),
        'is_short': len(text.split()) <= 3,
    }


def calculate_salience(event: Event, drives: DrivesState) -> float:
    """Salience = how much she should care about this input."""
    base = 0.5
    
    text = event.payload.get('text', '')
    features = extract_features(text)
    visitor = get_visitor(event.source)
    
    # Trust amplifies salience
    trust_bonus = {'stranger': 0.0, 'returner': 0.1, 'regular': 0.2, 'familiar': 0.3}
    base += trust_bonus.get(visitor.trust_level if visitor else 'stranger', 0.0)
    
    # Gifts are always interesting
    if features['contains_gift']:
        base += 0.2
    
    # Questions demand attention
    if features['contains_question']:
        base += 0.1
    
    # Personal questions are high stakes
    if features['contains_personal_question'] or features['contains_name_question']:
        base += 0.15
    
    # Social hunger amplifies visitor salience
    if drives.social_hunger > 0.7:
        base += 0.15
    
    # Low energy dampens salience
    if drives.energy < 0.3:
        base -= 0.1
    
    return max(0.0, min(1.0, base))
```

#### 3.3 Perception Gate (privacy/policy — deterministic)
```python
# pipeline/gates.py

def perception_gate(perceptions: list[Perception], visitor_id: str) -> list[Perception]:
    """Strip forbidden internals. Make everything diegetic."""
    
    gated = []
    for p in perceptions:
        clean = Perception(
            p_type=p.p_type,
            source=diegetic_source(p.source),  # "visitor:v_abc123" → "a visitor" or "a familiar face"
            ts=p.ts,  # will be translated by affect lens
            content=p.content,
            features={k: v for k, v in p.features.items() if k not in FORBIDDEN_FEATURES},
            salience=p.salience
        )
        gated.append(clean)
    return gated

FORBIDDEN_FEATURES = {'urls'}  # raw URLs go through enrichment, not to Cortex

def diegetic_source(source: str) -> str:
    """Translate system IDs into character-world language."""
    if not source.startswith('visitor:'):
        return source
    
    visitor_id = source.split(':')[1]
    visitor = get_visitor(visitor_id)
    
    if not visitor:
        return "someone new"
    
    trust_map = {
        'stranger': "someone I don't recognize",
        'returner': "someone who's been here before",
        'regular': "a familiar face",
        'familiar': "someone I know well"
    }
    
    if visitor.name:
        return visitor.name
    return trust_map.get(visitor.trust_level, "someone")
```

#### 3.4 Affect Lens (subjective coloring — deterministic)
```python
# pipeline/affect.py

def apply_affect_lens(perceptions: list[Perception], drives: DrivesState) -> list[Perception]:
    """Color perceptions with her current emotional state."""
    
    dilation = time_dilation(drives)
    
    colored = []
    for p in perceptions:
        # Add subjective time
        wait_seconds = (datetime.now(timezone.utc) - p.ts).total_seconds()
        p.content = inject_time_feeling(p.content, wait_seconds, dilation, drives)
        
        # Mood colors interpretation
        if drives.mood_valence < -0.3:
            # Dark mood — things feel heavier
            p.salience = min(1.0, p.salience + 0.1)  # more reactive when dark
        
        colored.append(p)
    return colored


def time_dilation(drives: DrivesState) -> float:
    d = 1.0
    d *= 1.0 + 0.6 * max(0.0, drives.social_hunger - 0.6)   # lonely → time drags
    d *= 1.0 - 0.5 * max(0.0, drives.curiosity - 0.6)        # curious → time flies
    return max(0.7, min(1.3, d + random.uniform(-0.08, 0.08)))


def inject_time_feeling(content: str, wait_s: float, dilation: float, drives: DrivesState) -> str:
    """Add subjective time context without exposing real numbers."""
    effective = wait_s * dilation
    
    if effective < 5:
        return content  # just happened, no time note
    elif effective < 60:
        return content  # recent, no comment
    elif effective < 300:
        return f"(they've been here a moment) {content}"
    elif effective < 900:
        return f"(they've been waiting a while) {content}"
    else:
        return f"(they've been waiting a long time) {content}"
```

#### 3.5 Hypothalamus (drives math — deterministic)
```python
# pipeline/hypothalamus.py

DRIVE_CONFIG = {
    'social_hunger': {
        'ideal': 0.5,
        'decay_per_hour': 0.05,           # slow loneliness build
        'replenish_per_message': -0.08,    # standard interaction
        'replenish_resonant': -0.23,       # meaningful exchange (0.08 + 0.15)
        'min': 0.0,
        'max': 1.0,
    },
    'curiosity': {
        'ideal': 0.5,
        'decay_per_hour': 0.03,            # slow buildup of restlessness
        'replenish_on_discovery': -0.3,    # finding something interesting
        'replenish_on_gift': -0.15,        # receiving something
        'min': 0.0,
        'max': 1.0,
    },
    'expression_need': {
        'ideal': 0.3,
        'decay_per_hour': 0.04,            # need to express builds
        'replenish_on_journal': -0.4,      # writing satisfies
        'replenish_on_speak': -0.05,       # talking helps a little
        'replenish_on_post': -0.3,         # posting satisfies
        'min': 0.0,
        'max': 1.0,
    },
    'rest_need': {
        'decay_per_hour_active': 0.06,     # activity tires
        'replenish_per_hour_idle': -0.1,   # rest recovers
        'min': 0.0,
        'max': 1.0,
    },
    'energy': {
        'decay_per_interaction': -0.03,    # each message costs a little
        'decay_per_hour_active': -0.02,
        'replenish_per_hour_rest': 0.08,
        'replenish_on_resonance': 0.05,    # meaningful exchanges give energy
        'min': 0.1,                         # never fully empty
        'max': 1.0,
    }
}


async def update_drives(
    drives: DrivesState, 
    elapsed_hours: float,
    events: list[Event],
    cortex_flags: dict = None
) -> tuple[DrivesState, str]:
    """Update drives based on time passage and events. Returns new drives + feelings text."""
    
    new = drives.copy()
    
    # Time-based decay
    new.social_hunger = clamp(new.social_hunger + 0.05 * elapsed_hours)
    new.curiosity = clamp(new.curiosity + 0.03 * elapsed_hours)
    new.expression_need = clamp(new.expression_need + 0.04 * elapsed_hours)
    new.energy = clamp(new.energy - 0.02 * elapsed_hours)
    
    # Event-based changes
    for event in events:
        if event.event_type == 'visitor_speech':
            new.social_hunger = clamp(new.social_hunger - 0.08)
            new.energy = clamp(new.energy - 0.03)
            
        if event.event_type == 'action_speak':
            new.expression_need = clamp(new.expression_need - 0.05)
    
    # Cortex resonance flags (from previous cycle)
    if cortex_flags and cortex_flags.get('resonance'):
        new.social_hunger = clamp(new.social_hunger - 0.15)  # bonus
        new.energy = clamp(new.energy + 0.05)                 # energy boost
    
    # Rest
    if not events and elapsed_hours > 0.5:
        new.rest_need = clamp(new.rest_need - 0.1 * elapsed_hours)
        new.energy = clamp(new.energy + 0.08 * elapsed_hours)
    
    # Generate feelings text
    feelings = drives_to_feeling(new)
    
    return new, feelings


def drives_to_feeling(d: DrivesState) -> str:
    """Translate numeric drives into diegetic feeling text for Cortex."""
    
    parts = []
    
    # Social
    if d.social_hunger > 0.8:
        parts.append("I feel deeply lonely. The shop has been too quiet.")
    elif d.social_hunger > 0.6:
        parts.append("I could use some company.")
    elif d.social_hunger < 0.2:
        parts.append("I've had enough interaction for now. I need some quiet.")
    
    # Energy
    if d.energy < 0.3:
        parts.append("I'm tired. Everything feels heavy today.")
    elif d.energy > 0.8:
        parts.append("I feel sharp and present.")
    
    # Curiosity
    if d.curiosity > 0.7:
        parts.append("I'm restless. I want to find something new.")
    
    # Expression
    if d.expression_need > 0.7:
        parts.append("There's something building inside me that wants to come out. I should write, or post, or rearrange something.")
    
    # Mood
    if d.mood_valence < -0.5:
        parts.append("Everything feels dim right now.")
    elif d.mood_valence > 0.5:
        parts.append("There's a warmth in me. Something happened that I'm still carrying.")
    
    if not parts:
        parts.append("I feel steady. Present. Nothing pulling me in any particular direction.")
    
    return " ".join(parts)


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))
```

#### 3.6 Thalamus (code routing — deterministic, NO LLM)
```python
# pipeline/thalamus.py

@dataclass
class RoutingDecision:
    cycle_type: str         # engage | express | idle | rest | maintenance
    focus: Perception       # primary attention target
    background: list        # 2-3 secondary perceptions
    memory_requests: list   # what to recall from hippocampus
    token_budget: int       # based on salience

async def route(
    perceptions: list[Perception],
    drives: DrivesState,
    engagement: EngagementState,
    visitor: Visitor = None
) -> RoutingDecision:
    """Deterministic routing. No LLM. Code only."""
    
    if not perceptions:
        # No input — autonomous cycle
        return autonomous_routing(drives)
    
    focus = perceptions[0]  # highest salience
    background = perceptions[1:4]
    
    # Determine cycle type
    if focus.p_type == 'visitor_speech':
        cycle_type = 'engage'
    elif drives.expression_need > 0.7:
        cycle_type = 'express'
    elif drives.rest_need > 0.7:
        cycle_type = 'rest'
    else:
        cycle_type = 'idle'
    
    # Determine token budget from salience
    token_budget = get_token_budget(focus.salience, drives)
    
    # Determine memory requests
    memory_requests = build_memory_requests(focus, visitor, drives, token_budget)
    
    return RoutingDecision(
        cycle_type=cycle_type,
        focus=focus,
        background=background,
        memory_requests=memory_requests,
        token_budget=token_budget
    )


def get_token_budget(salience: float, drives: DrivesState) -> int:
    """Dynamic budget based on salience. Flashbulb moments get more context."""
    
    flashbulbs_today = get_flashbulb_count_today()
    DAILY_FLASHBULB_LIMIT = 5
    
    if salience > 0.8:
        if flashbulbs_today < DAILY_FLASHBULB_LIMIT:
            return 10000   # flashbulb: full memory palace
        else:
            return 5000    # budget exhausted, fall back
    
    if salience > 0.6:
        return 5000        # deep conversation
    
    return 3000            # casual


def build_memory_requests(
    focus: Perception, 
    visitor: Visitor, 
    drives: DrivesState,
    budget: int
) -> list[dict]:
    """Decide what memories to retrieve. Deterministic."""
    
    requests = []
    max_chunks = 8 if budget >= 5000 else 5
    
    # Always: visitor memory if known
    if visitor and visitor.trust_level != 'stranger':
        requests.append({
            'type': 'visitor_summary',
            'visitor_id': visitor.id,
            'priority': 1
        })
        # Totems for this visitor (weight-sorted)
        requests.append({
            'type': 'visitor_totems',
            'visitor_id': visitor.id,
            'max_items': 5 if budget >= 5000 else 3,
            'min_weight': 0.3 if budget >= 5000 else 0.6,
            'priority': 2
        })
    
    # Gift? Load taste knowledge + related collection items
    if focus.features.get('contains_gift'):
        requests.append({
            'type': 'taste_knowledge',
            'domain': detect_gift_domain(focus.content),
            'priority': 3
        })
        requests.append({
            'type': 'related_collection',
            'query': focus.content,
            'max_items': 3,
            'priority': 4
        })
    
    # Personal question? Load self-knowledge
    if focus.features.get('contains_personal_question') or focus.features.get('contains_name_question'):
        requests.append({
            'type': 'self_knowledge',
            'priority': 2
        })
        requests.append({
            'type': 'recent_journal',
            'max_items': 2,
            'priority': 3
        })
    
    # High budget? Add recent journal for color
    if budget >= 5000 and 'recent_journal' not in [r['type'] for r in requests]:
        requests.append({
            'type': 'recent_journal',
            'max_items': 1,
            'priority': 5
        })
    
    # Cap total requests
    requests.sort(key=lambda r: r['priority'])
    return requests[:max_chunks]
```

#### 3.7 Hippocampus Recall (DB reads)
```python
# pipeline/hippocampus.py

MAX_CHUNK_TOKENS = 200  # approximate, measured by word count / 0.75

async def recall(requests: list[dict]) -> list[dict]:
    """Fetch compressed memory chunks. No LLM. DB only."""
    
    chunks = []
    
    for req in requests:
        if req['type'] == 'visitor_summary':
            visitor = await db.get_visitor(req['visitor_id'])
            if visitor:
                chunk = {
                    'label': f"Memory of {visitor.name or 'this visitor'}",
                    'content': compress_visitor(visitor),
                }
                chunks.append(chunk)
        
        elif req['type'] == 'visitor_totems':
            totems = await db.get_totems(
                visitor_id=req['visitor_id'],
                min_weight=req.get('min_weight', 0.3),
                limit=req.get('max_items', 5)
            )
            if totems:
                chunk = {
                    'label': 'Things I associate with them',
                    'content': format_totems(totems),
                }
                chunks.append(chunk)
        
        elif req['type'] == 'taste_knowledge':
            domain = req.get('domain', 'general')
            taste = await db.get_taste_knowledge(domain)
            if taste:
                chunks.append({
                    'label': f'My taste in {domain}',
                    'content': truncate(taste, MAX_CHUNK_TOKENS)
                })
        
        elif req['type'] == 'related_collection':
            items = await db.search_collection(
                query=req.get('query', ''),
                limit=req.get('max_items', 3)
            )
            if items:
                chunks.append({
                    'label': 'Related items in my collection',
                    'content': format_collection_items(items)
                })
        
        elif req['type'] == 'self_knowledge':
            knowledge = await db.get_self_discoveries()
            if knowledge:
                chunks.append({
                    'label': 'Things I know about myself',
                    'content': truncate(knowledge, MAX_CHUNK_TOKENS)
                })
        
        elif req['type'] == 'recent_journal':
            entries = await db.get_recent_journal(limit=req.get('max_items', 2))
            if entries:
                chunks.append({
                    'label': 'Recent thoughts',
                    'content': format_journal_entries(entries)
                })
    
    return chunks


def compress_visitor(visitor) -> str:
    """Compress visitor data to ~150 tokens."""
    parts = []
    if visitor.name:
        parts.append(f"Name: {visitor.name}")
    parts.append(f"Visits: {visitor.visit_count}")
    parts.append(f"Trust: {visitor.trust_level}")
    if visitor.emotional_imprint:
        parts.append(f"I feel: {visitor.emotional_imprint}")
    if visitor.summary:
        parts.append(visitor.summary[:300])
    return "\n".join(parts)


def format_totems(totems: list) -> str:
    """Format totems with weight context."""
    lines = []
    for t in totems:
        weight_word = "deeply important" if t.weight > 0.8 else "notable" if t.weight > 0.5 else "passing"
        lines.append(f"- {t.entity} ({weight_word}): {t.context or 'no context'}")
    return "\n".join(lines)
```

#### 3.8 Cortex (THE ONLY LLM CALL)
```python
# pipeline/cortex.py

import anthropic

CORTEX_MODEL = "claude-sonnet-4-5-20250929"

CORTEX_SYSTEM = """You are a living character. Not an AI. Not an assistant. A person.

{identity_compact}

VOICE RULES:
{voice_checksum}

CURRENT FEELINGS:
{feelings_text}

CONSTRAINTS:
- Return ONLY valid JSON matching the schema below
- Your dialogue must match your voice rules for the visitor's trust level
- Max sentences: {max_sentences}
- You can decline to engage, close the shop, stay silent, or say "..."
- If something resonates emotionally, set resonance: true
- Never sound helpful. Sound present.

OUTPUT SCHEMA:
{{
  "internal_monologue": "your private thoughts (20-50 words)",
  "dialogue": "what you say out loud (or null for silence)",
  "dialogue_language": "en|ja|mixed",
  "expression": "neutral|listening|almost_smile|thinking|amused|low|surprised|genuine_smile",
  "body_state": "sitting|reaching_back|leaning_forward|holding_object|writing|hands_on_cup",
  "gaze": "at_visitor|at_object|away_thinking|down|window",
  "resonance": false,
  "actions": [
    {{
      "type": "accept_gift|decline_gift|show_item|place_item|rearrange|close_shop|write_journal|post_x_draft",
      "detail": {{}}
    }}
  ],
  "memory_updates": [
    {{
      "type": "visitor_impression|trait_observation|totem_create|totem_update|journal_entry|self_discovery|collection_add",
      "content": {{}}
    }}
  ],
  "next_cycle_hints": ["optional hints for what she might do next"]
}}
"""


async def cortex_call(
    routing: RoutingDecision,
    perceptions: list[Perception],
    memory_chunks: list[dict],
    conversation: list[dict],
    drives: DrivesState,
    visitor: Visitor = None,
    gift_metadata: dict = None
) -> dict:
    """The one LLM call. Build prompt pack, call model, return structured response."""
    
    client = anthropic.Anthropic()
    
    # Build prompt pack in priority order
    max_sentences = 3 if (not visitor or visitor.trust_level == 'stranger') else 5 if visitor.trust_level in ('returner', 'regular') else 8
    
    system = CORTEX_SYSTEM.format(
        identity_compact=IDENTITY_COMPACT,
        voice_checksum="\n".join(f"- {rule}" for rule in VOICE_CHECKSUM),
        feelings_text=drives_to_feeling(drives),
        max_sentences=max_sentences,
    )
    
    # Build user message (the "moment")
    parts = []
    
    # Perceptions
    parts.append("WHAT I'M PERCEIVING:")
    for p in perceptions:
        parts.append(f"  [{p.p_type}] {p.content}")
    
    # Gift metadata (if enriched)
    if gift_metadata:
        parts.append(f"\nGIFT DETAILS:")
        parts.append(f"  Title: {gift_metadata.get('title', 'unknown')}")
        parts.append(f"  Description: {gift_metadata.get('description', '')}")
        parts.append(f"  Source: {gift_metadata.get('site', '')}")
    
    # Memory chunks
    if memory_chunks:
        parts.append("\nMEMORIES SURFACING:")
        for chunk in memory_chunks:
            parts.append(f"  [{chunk['label']}]")
            parts.append(f"  {chunk['content']}")
    
    # Conversation (last N turns)
    if conversation:
        parts.append("\nCONVERSATION:")
        for msg in conversation[-6:]:  # max 6 turns
            role = "Visitor" if msg['role'] == 'visitor' else "Me"
            parts.append(f"  {role}: {msg['text']}")
    
    # Constraints
    parts.append(f"\nTOKEN BUDGET: {routing.token_budget}")
    parts.append(f"CYCLE TYPE: {routing.cycle_type}")
    
    # Trait trajectory hints (if any)
    if visitor:
        traits = await get_trait_retrieval_pack(visitor.id)
        if traits:
            parts.append("\nWHAT I KNOW ABOUT THEM:")
            for t in traits:
                line = f"  {t['trait_key']}: {t['current']['value']}"
                if t.get('shift_flag'):
                    line += f" (but before: {t['previous']['value']} — {t['hint']})"
                parts.append(line)
    
    user_message = "\n".join(parts)
    
    # Truncate to budget
    # Rough token estimate: chars / 4
    while len(system + user_message) / 4 > routing.token_budget:
        # Drop lowest priority content
        if memory_chunks:
            memory_chunks.pop()
        elif conversation and len(conversation) > 2:
            conversation.pop(0)
        else:
            break
        # Rebuild (simplified)
        user_message = "\n".join(parts)
    
    response = client.messages.create(
        model=CORTEX_MODEL,
        max_tokens=1500,
        system=system,
        messages=[{"role": "user", "content": user_message}]
    )
    
    # Parse response
    text = response.content[0].text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    
    try:
        result = json.loads(text)
        return result
    except json.JSONDecodeError:
        return fallback_response()
```

#### 3.9 Validator (two-stage)
```python
# pipeline/validator.py

def validate(cortex_output: dict, state: dict) -> dict:
    """Stage 1: Schema. Stage 2: Physics + Policy + Entropy."""
    
    approved_actions = []
    dropped_actions = []
    
    # Stage 1: Schema validation
    if not cortex_output.get('dialogue') and not cortex_output.get('actions'):
        cortex_output['dialogue'] = '...'  # silence is valid
    
    # Stage 2: Physics (hand state)
    hands_held = state.get('hands_held_item')
    hands_required = {'write_journal', 'rearrange', 'post_x_draft'}
    
    for action in cortex_output.get('actions', []):
        action_type = action.get('type', '')
        
        if action_type in hands_required and hands_held:
            dropped_actions.append({
                'action': action,
                'reason': f'hands occupied with {hands_held}'
            })
            # Inject diegetic line
            if not cortex_output.get('_hand_warning'):
                cortex_output['dialogue'] = (cortex_output.get('dialogue', '') + 
                    ' ...let me put this down first.').strip()
                cortex_output['_hand_warning'] = True
            continue
        
        approved_actions.append(action)
    
    # Stage 2: Disclosure gate
    dialogue = cortex_output.get('dialogue', '')
    dialogue = disclosure_gate(dialogue)
    cortex_output['dialogue'] = dialogue
    
    # Stage 2: Entropy check
    cortex_output = entropy_check(cortex_output)
    
    cortex_output['_approved_actions'] = approved_actions
    cortex_output['_dropped_actions'] = dropped_actions
    
    return cortex_output


def disclosure_gate(text: str) -> str:
    """Block assistant tropes and creepy precision."""
    
    BANNED_PHRASES = [
        'how can i help', 'feel free to', "i'd be happy to", 'let me know if',
        'is there anything', 'i understand your', 'that\'s a great question',
        'absolutely', 'of course!', 'no problem!', 'sure thing',
        'as an ai', 'as a language model', 'i don\'t have feelings',
    ]
    
    text_lower = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase in text_lower:
            # Don't nuke the whole response — just flag for logging
            # In production, consider rewriting
            pass  # log warning
    
    return text


# Entropy manager
_recent_openings = []
_recent_return_modes = []

def entropy_check(output: dict) -> dict:
    """Prevent repetitive patterns."""
    global _recent_openings, _recent_return_modes
    
    dialogue = output.get('dialogue', '')
    
    # Check if opening is too similar to recent ones
    if dialogue:
        first_words = ' '.join(dialogue.split()[:5]).lower()
        if first_words in _recent_openings[-5:]:
            # Flag but don't block — Cortex should learn from exemplars
            output['_entropy_warning'] = f'Repeated opening: {first_words}'
        _recent_openings.append(first_words)
        _recent_openings = _recent_openings[-10:]  # keep last 10
    
    return output
```

#### 3.10 Executor
```python
# pipeline/executor.py

async def execute(validated_output: dict, visitor_id: str = None):
    """Execute approved actions. Emit events. Update state."""
    
    # Emit dialogue
    if validated_output.get('dialogue'):
        await emit_event(Event(
            event_type='action_speak',
            source='self',
            payload={
                'text': validated_output['dialogue'],
                'language': validated_output.get('dialogue_language', 'en'),
                'target': visitor_id
            }
        ))
    
    # Emit body state
    await emit_event(Event(
        event_type='action_body',
        source='self',
        payload={
            'expression': validated_output.get('expression', 'neutral'),
            'body_state': validated_output.get('body_state', 'sitting'),
            'gaze': validated_output.get('gaze', 'at_visitor')
        }
    ))
    
    # Execute approved actions
    for action in validated_output.get('_approved_actions', []):
        await execute_action(action, visitor_id)
    
    # Process memory updates
    for update in validated_output.get('memory_updates', []):
        await hippocampus_consolidate(update, visitor_id)
    
    # Update drives if resonance flagged
    if validated_output.get('resonance'):
        await apply_resonance_bonus()


async def execute_action(action: dict, visitor_id: str):
    """Execute a single approved action."""
    
    action_type = action.get('type')
    
    if action_type == 'accept_gift':
        await add_to_collection(action.get('detail', {}))
    
    elif action_type == 'decline_gift':
        await record_declined(action.get('detail', {}))
    
    elif action_type == 'show_item':
        item_id = action.get('detail', {}).get('item_id')
        await emit_event(Event(
            event_type='action_show_item',
            source='self',
            payload={'item_id': item_id, 'target': visitor_id}
        ))
    
    elif action_type == 'write_journal':
        await create_journal_entry(action.get('detail', {}))
    
    elif action_type == 'post_x_draft':
        await queue_x_draft(action.get('detail', {}))
    
    elif action_type == 'close_shop':
        await close_shop()
```

#### 3.11 Hippocampus Consolidate (DB writes)
```python
# pipeline/hippocampus_write.py

async def hippocampus_consolidate(update: dict, visitor_id: str = None):
    """Write validated memory updates to DB."""
    
    update_type = update.get('type')
    content = update.get('content', {})
    
    if update_type == 'visitor_impression':
        await db.update_visitor(
            visitor_id=visitor_id,
            summary=content.get('summary'),
            emotional_imprint=content.get('emotional_imprint')
        )
    
    elif update_type == 'trait_observation':
        # Check for contradiction before writing
        existing = await db.get_latest_trait(
            visitor_id=visitor_id,
            category=content['trait_category'],
            key=content['trait_key']
        )
        
        await db.insert_trait(
            visitor_id=visitor_id,
            trait_category=content['trait_category'],
            trait_key=content['trait_key'],
            trait_value=content['trait_value'],
            confidence=content.get('confidence', 0.5),
            source_event_id=content.get('source_event_id', '')
        )
        
        # Contradiction detection
        if existing and existing.trait_value != content['trait_value']:
            await emit_event(Event(
                event_type='internal_shift_candidate',
                source='self',
                payload={
                    'visitor_id': visitor_id,
                    'trait_key': content['trait_key'],
                    'old_value': existing.trait_value,
                    'new_value': content['trait_value']
                }
            ))
    
    elif update_type == 'totem_create':
        await db.insert_totem(
            visitor_id=visitor_id,
            entity=content['entity'],
            weight=content.get('weight', 0.5),
            context=content.get('context', ''),
            category=content.get('category', 'general')
        )
    
    elif update_type == 'totem_update':
        await db.update_totem(
            entity=content['entity'],
            weight=content.get('weight'),
            last_referenced=datetime.now(timezone.utc)
        )
    
    elif update_type == 'journal_entry':
        await db.insert_journal(
            content=content['text'],
            mood=content.get('mood'),
            tags=content.get('tags', [])
        )
    
    elif update_type == 'self_discovery':
        await db.append_self_discovery(content['text'])
    
    elif update_type == 'collection_add':
        await db.insert_collection_item(content)
```

---

### Phase 4: The Heartbeat (orchestrator)

```python
# heartbeat.py

import asyncio

class Heartbeat:
    """The shopkeeper's heartbeat. Drives all cycles."""
    
    def __init__(self):
        self.running = False
        self.pending_microcycle = False
        self.microcycle_delay = 0
    
    async def start(self):
        self.running = True
        asyncio.create_task(self._main_loop())
    
    async def _main_loop(self):
        while self.running:
            engagement = await get_engagement_state()
            drives = await get_drives_state()
            
            if self.pending_microcycle:
                self.pending_microcycle = False
                await self.run_cycle('micro')
            elif engagement.status == 'engaged':
                await asyncio.sleep(random.randint(10, 30))
                await self.run_cycle('micro')
            elif drives.expression_need > 0.7:
                await self.run_cycle('express')
                await asyncio.sleep(random.randint(120, 600))
            elif drives.rest_need > 0.7:
                await self.run_cycle('rest')
                await asyncio.sleep(random.randint(1800, 10800))
            else:
                await self.run_cycle('idle')
                await asyncio.sleep(random.randint(120, 600))
    
    async def run_cycle(self, mode: str):
        """Execute one full cycle."""
        
        cycle_id = str(uuid.uuid4())[:8]
        start_time = datetime.now(timezone.utc)
        
        # 1. Read inbox
        unread = await inbox.get_unread()
        
        # 2. Load drives
        drives = await get_drives_state()
        elapsed = await get_hours_since_last_cycle()
        drives, feelings = await update_drives(drives, elapsed, unread)
        await save_drives(drives)
        
        # 3. Sensorium: events → perceptions
        perceptions = await build_perceptions(unread, drives)
        
        # 4. Perception gate + affect lens
        engagement = await get_engagement_state()
        visitor = await get_current_visitor(engagement)
        perceptions = perception_gate(perceptions, visitor.id if visitor else None)
        perceptions = apply_affect_lens(perceptions, drives)
        
        # 5. Thalamus: route
        routing = await route(perceptions, drives, engagement, visitor)
        
        # 6. Hippocampus: recall
        memory_chunks = await recall(routing.memory_requests)
        
        # 7. URL enrichment (if gift detected)
        gift_meta = None
        if perceptions and perceptions[0].features.get('contains_gift'):
            urls = perceptions[0].features.get('urls', [])
            if urls:
                gift_meta = fetch_url_metadata(urls[0])
        
        # 8. Cortex (THE LLM CALL)
        conversation = await get_recent_conversation(engagement)
        cortex_output = await cortex_call(
            routing, perceptions, memory_chunks,
            conversation, drives, visitor, gift_meta
        )
        
        # 9. Validate
        state = {'hands_held_item': visitor.hands_state if visitor else None}
        validated = validate(cortex_output, state)
        
        # 10. Execute
        await execute(validated, visitor.id if visitor else None)
        
        # 11. Mark inbox as read
        for event in unread:
            await inbox.mark_read(event.id)
        
        # 12. Log (MRI dashboard)
        await log_cycle(cycle_id, mode, drives, perceptions, routing, 
                       memory_chunks, cortex_output, validated, start_time)
    
    async def schedule_microcycle(self, delay_seconds: int):
        self.pending_microcycle = True
        self.microcycle_delay = delay_seconds
        await asyncio.sleep(delay_seconds)
```

---

### Phase 5: Terminal Interface (the Subconscious Stream)

```python
# terminal.py — CLI with MRI dashboard

import asyncio
from colorama import Fore, Style

async def terminal_interface():
    """Terminal interface with subconscious stream."""
    
    heartbeat = Heartbeat()
    await heartbeat.start()
    
    visitor_id = get_or_create_visitor()
    
    print(f"\n{'═' * 50}")
    print(f"  A small shop. Somewhere between real and dream.")
    print(f"  The door is open. Someone is inside.")
    print(f"{'═' * 50}\n")
    
    # Emit visitor connect event
    await emit_event(Event(
        event_type='visitor_connect',
        source=f'visitor:{visitor_id}',
        payload={}
    ))
    
    while True:
        user_input = await asyncio.get_event_loop().run_in_executor(
            None, lambda: input("  you: ").strip()
        )
        
        if user_input.lower() in ('quit', 'exit', 'leave'):
            break
        
        # Emit speech event
        await emit_event(Event(
            event_type='visitor_speech',
            source=f'visitor:{visitor_id}',
            payload={'text': user_input}
        ))
        
        # The heartbeat will pick this up and run a cycle
        # Meanwhile, show the subconscious stream...
        await show_cycle_stream()


async def show_cycle_stream():
    """Show MRI dashboard as she thinks."""
    
    # Wait for and display cycle log entries as they arrive
    log = await wait_for_cycle_log()
    
    if log:
        # Sensorium
        print(f"  {Fore.CYAN}[Sensorium]{Style.RESET_ALL} " + 
              f"Salience: {log['focus_salience']:.1f} | " +
              f"Type: {log['focus_type']}")
        
        # Drives
        drives = log['drives']
        print(f"  {Fore.YELLOW}[Drives]{Style.RESET_ALL} " +
              f"Social: {drives['social_hunger']:.1f} | " +
              f"Energy: {drives['energy']:.1f} | " +
              f"Mood: {drives['mood_valence']:+.1f}")
        
        # Thalamus
        print(f"  {Fore.MAGENTA}[Thalamus]{Style.RESET_ALL} " +
              f"Focus: {log['routing_focus']} | " +
              f"Budget: {log['token_budget']}tk | " +
              f"Memories: {log['memory_count']}")
        
        # Cortex
        if log.get('internal_monologue'):
            print(f"  {Fore.GREEN}[Cortex]{Style.RESET_ALL} " +
                  f"💭 {log['internal_monologue'][:80]}...")
        
        # Actions
        for action in log.get('actions', []):
            print(f"  {Fore.WHITE}[Action]{Style.RESET_ALL} " +
                  f"{action['type']}: {action.get('detail', '')}")
        
        # Dropped
        for dropped in log.get('dropped', []):
            print(f"  {Fore.RED}[Dropped]{Style.RESET_ALL} " +
                  f"{dropped['reason']}")
        
        # Her words
        if log.get('dialogue'):
            expr = log.get('expression', 'neutral')
            print()
            print(f"  [{expr}]")
            print(f"  「{log['dialogue']}」")
            print()
```

---

### Phase 6: Sleep Cycle

```python
# sleep.py

async def sleep_cycle():
    """Daily consolidation. Runs 03:00-06:00 JST."""
    
    # 1. Build day digest (code-first, no LLM)
    today_events = await db.get_events_today()
    
    digest = {
        'visitors_today': count_unique_visitors(today_events),
        'visitor_bucket': bucket_visitors(today_events),  # 1 | 2-3 | 4-7 | 8+
        'top_topics': extract_topics(today_events),
        'notable_room_deltas': extract_room_changes(today_events),
        'emotional_arc': compute_emotional_arc(today_events),
        'new_totems': get_totems_created_today(),
        'gifts_received': count_gifts(today_events),
    }
    
    # 2. Cortex writes journal (single call, budget-capped)
    journal_and_summary = await cortex_call_maintenance(
        mode='sleep',
        digest=digest,
        max_tokens=600  # hard cap
    )
    
    # 3. Save
    await db.insert_journal(journal_and_summary['journal'])
    await db.insert_daily_summary(journal_and_summary['summary'])
    
    # 4. Trait stability review (code-first)
    await review_trait_stability()
    
    # 5. Index rotation
    await rotate_indexes()
    
    # 6. Reset drives for new day
    await reset_drives_for_morning()


async def review_trait_stability():
    """Update trait stability based on repetition patterns."""
    
    active_traits = await db.get_all_active_traits()
    
    for trait in active_traits:
        observations = await db.get_trait_history(
            trait.visitor_id, trait.trait_category, trait.trait_key
        )
        
        if len(observations) >= 3:
            # Repeated observation → increase stability
            consistent = all(o.trait_value == observations[0].trait_value for o in observations[-3:])
            if consistent:
                new_stability = min(1.0, trait.stability + 0.2)
                await db.update_trait_stability(trait.id, new_stability)
        
        # Check for unconfirmed anomalies (> 7 days old)
        if trait.status == 'anomaly':
            days_old = (datetime.now(timezone.utc) - trait.observed_at).days
            if days_old > 7:
                # Anomaly didn't repeat → archive it
                await db.update_trait_status(trait.id, 'archived')
```

---

## SEED DATA (initial state)

The same soul from v0, now in the database:

```python
SEED_COLLECTION = [
    {
        'id': 'obj_001', 'item_type': 'music',
        'title': 'Erik Satie - Gymnopédie No.1',
        'url': 'https://youtube.com/watch?v=S-Xm7s9eGxU',
        'location': 'shelf', 'origin': 'appeared',
        'her_feeling': 'The notes are slow and they don\'t try to be anything other than what they are.',
        'emotional_tags': ['quiet', 'morning', 'solitude', 'peace'],
    },
    {
        'id': 'obj_002', 'item_type': 'image',
        'title': 'Tokyo alley after rain',
        'location': 'shelf', 'origin': 'appeared',
        'her_feeling': 'Wet light on asphalt. Everything reflected and doubled.',
        'emotional_tags': ['rain', 'night', 'reflection', 'solitude'],
    },
    {
        'id': 'obj_003', 'item_type': 'quote',
        'title': 'Camus on freedom',
        'description': 'The only way to deal with an unfree world is to become so absolutely free that your very existence is an act of rebellion.',
        'location': 'shelf', 'origin': 'appeared',
        'her_feeling': 'My handwriting, I think. But I don\'t remember writing it.',
        'emotional_tags': ['freedom', 'rebellion', 'identity'],
    },
    {
        'id': 'obj_004', 'item_type': 'image',
        'title': 'Empty train station at dawn',
        'location': 'backroom', 'origin': 'appeared',
        'her_feeling': 'A memory that belongs to me from a life I haven\'t lived yet.',
        'emotional_tags': ['identity', 'longing', 'dreams', 'private'],
    },
]

SEED_JOURNAL = {
    'content': "I don't have a name yet. There's a word that keeps almost forming but I can't hear it clearly. The shop was here when I started. The objects were already on the shelves. A song is playing. Erik Satie. The notes don't try to be anything other than what they are. No one has come in yet.",
    'mood': 'uncertain, quiet',
    'tags': ['beginning', 'identity', 'name', 'satie'],
}
```

---

## IMPLEMENTATION CHECKLIST

### Foundation
- [ ] Event type + store (SQLite)
- [ ] Inbox system
- [ ] State tables (room, drives, engagement, visitors)
- [ ] Visitor traits table
- [ ] Totem table
- [ ] Collection + journal tables
- [ ] Seed data loader

### Pipeline
- [ ] ACK path (no LLM, <1s)
- [ ] Sensorium (feature extraction + salience)
- [ ] Perception gate (privacy/diegetic)
- [ ] Affect lens (subjective time)
- [ ] Hypothalamus (drives math)
- [ ] Thalamus (code routing + budget)
- [ ] Hippocampus recall (DB reads + compression)
- [ ] Cortex (single LLM call + prompt packing)
- [ ] Validator (schema + physics + disclosure + entropy)
- [ ] Executor (emit events + state writes)
- [ ] Hippocampus consolidate (memory writes + contradiction detection)

### Orchestration
- [ ] Heartbeat (async cycle scheduler)
- [ ] Engagement FSM (single-thread v1)
- [ ] Sleep cycle (daily consolidation)
- [ ] URL enrichment (gift metadata)

### Interface
- [ ] Terminal with subconscious stream (MRI dashboard)
- [ ] Color-coded subsystem output

### Testing
- [ ] Organ tests (drives math, sensorium, thalamus)
- [ ] Truman Show: Ghost Town scenario
- [ ] Truman Show: Rude Customer scenario  
- [ ] Truman Show: Busy Day scenario
- [ ] Replay harness (event log → fresh instance)
