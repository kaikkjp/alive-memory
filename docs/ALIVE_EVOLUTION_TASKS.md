# ALIVE Evolution Tasks — Self-Modifying Cognitive Architecture

> These four tasks transform The Shopkeeper from a static character engine into a system that evolves its own cognitive architecture through experience.
>
> **Dependency order:** TASK-054 (bug fix, standalone) → TASK-055 (infrastructure) → TASK-056 (depends on 055) → TASK-057 (standalone, can parallel with 055/056)

---

## TASK-054: Fix inhibition self_assessment trigger

**Status:** READY
**Priority:** High (bug fix)
**Complexity:** Small — 1 file change + migration
**Branch:** `fix/inhibition-self-assessment`

### Problem

Inhibitions form from `self_assessment` trigger within the first 25 minutes of existence. The cortex expresses normal introspective doubt ("I keep writing but nothing changes"), and the inhibition system interprets that self-criticism as "this action had a bad outcome." Result:

- `write_journal` inhibited when `visitor_present=false` — strength 0.750 (sim), 0.300 (prod)
- `express_thought` inhibited when `visitor_present=false` — same
- These match **95% of all cycles** since she's alone most of the time
- 244 blocked attempts in 7-day simulation, ~31% of her core creative output suppressed

The inhibition system was designed for external signals ("visitor left annoyed after aggressive recommendation"), not internal self-doubt.

### Root Cause

In `pipeline/output.py`, the negative signal detector treats `self_assessment` as a valid trigger for inhibition formation. The cortex's own reflective dissatisfaction feeds back into the inhibition system, creating a self-silencing loop.

### Implementation

**1. `pipeline/output.py` — Exclude self_assessment from inhibition triggers**

Find the negative signal detection logic that forms inhibitions. Add `self_assessment` to an exclusion list. Inhibitions should only form from:
- `visitor_displeasure` — visitor expressed unhappiness
- `visitor_departure` — visitor left quickly after action
- `action_failure` — action literally failed (not "incapable", which is different)
- `external_conflict` — action created observable negative consequence

Explicitly EXCLUDE from inhibition formation:
- `self_assessment` — her own introspective doubt
- `mood_decline` — feeling worse after an action (correlation ≠ causation)
- `repetition` — doing the same thing often (that's what habits are for, not inhibitions)

**2. Migration: Clear existing broken inhibitions**

```sql
-- Delete inhibitions formed from self_assessment
DELETE FROM inhibitions WHERE reason LIKE '%self_assessment%';
```

Run this on prod DB after deploy. The system will form correct inhibitions from real signals going forward.

**3. Add minimum-cycle guard**

No inhibitions should form in the first 100 cycles of a fresh database. Add a cycle count check:
```python
if db.get_cycle_count() < 100:
    return  # Too early to form inhibitions
```

This prevents the system from over-fitting to startup behavior before she has real experience.

### Scope

**Files to touch:**
- `pipeline/output.py` (inhibition formation logic)
- `migrations/` (new migration to clear broken inhibitions)

**Files NOT to touch:**
- `pipeline/basal_ganglia.py` (inhibition *checking* is fine, formation is the bug)
- `pipeline/cortex.py`
- `heartbeat.py`

### Tests

- Unit test: verify `self_assessment` trigger does NOT create inhibition
- Unit test: verify `visitor_displeasure` trigger DOES create inhibition
- Unit test: verify no inhibitions form before cycle 100
- Integration: run 200 cycles in test, confirm no inhibitions on `write_journal` when alone

### Definition of Done

- No inhibitions form from `self_assessment` trigger
- Existing broken inhibitions cleared from prod
- She journals and expresses thoughts freely when alone
- Inhibitions still form correctly from visitor interactions

---

## TASK-055: Extract pipeline parameters to self_parameters DB table

**Status:** BACKLOG (do after TASK-054)
**Priority:** High (infrastructure for TASK-056)
**Complexity:** Large — touches every pipeline module
**Branch:** `feat/self-parameters`

### Problem

All cognitive architecture constants are hardcoded in Python files:
- Drive equilibria in `pipeline/hypothalamus.py` (social_hunger=0.50, curiosity=0.50, etc.)
- Routing thresholds in `pipeline/thalamus.py` (engage_threshold=0.6, idle_threshold=0.3, etc.)
- Salience weights in `pipeline/sensorium.py` (visitor=0.70, content=0.60, conflict=0.80, etc.)
- Gate parameters in `pipeline/basal_ganglia.py` (impulse_threshold=0.3, cooldown multipliers, etc.)
- Inhibition formation rates in `pipeline/output.py` (strength_increment=0.15, decay_rate=0.10, etc.)
- Sleep consolidation parameters in `sleep.py` (top_n moments, reflection depth, etc.)

Currently only 2 values in `settings` table (cycle_interval, daily_budget). For self-modification, she needs ~50+ parameters accessible and modifiable at runtime.

### Implementation

**1. New table: `self_parameters`**

```sql
CREATE TABLE self_parameters (
    key TEXT PRIMARY KEY,                    -- e.g. "drives.social_hunger.equilibrium"
    value REAL NOT NULL,                     -- current value
    default_value REAL NOT NULL,             -- original value (for rollback)
    min_bound REAL NOT NULL,                 -- she can't go below this
    max_bound REAL NOT NULL,                 -- she can't go above this
    category TEXT NOT NULL,                  -- "drives", "routing", "salience", "gates", "inhibition", "sleep", "identity"
    description TEXT,                        -- human-readable: "How lonely she gets at equilibrium"
    modified_by TEXT DEFAULT 'system',       -- "system" or "self"
    modified_at TIMESTAMP,
    modification_reason TEXT                 -- her own words when she changed it
);

CREATE INDEX idx_sp_category ON self_parameters(category);
```

**2. Seed with current hardcoded values**

Migration seeds all current constants with their hardcoded values as both `value` and `default_value`. Bounds are set conservatively:

```
-- Drive equilibria
drives.social_hunger.equilibrium    | 0.50 | min=0.20 | max=0.80
drives.curiosity.equilibrium        | 0.50 | min=0.20 | max=0.80
drives.expression_need.equilibrium  | 0.35 | min=0.10 | max=0.70
drives.rest_need.equilibrium        | 0.25 | min=0.10 | max=0.50
drives.energy.equilibrium           | 0.70 | min=0.40 | max=0.90
drives.mood_valence.equilibrium     | 0.05 | min=-0.30 | max=0.50
drives.mood_arousal.equilibrium     | 0.30 | min=0.10 | max=0.70

-- Homeostatic pull rates
drives.social_hunger.pull_rate      | 0.02 | min=0.005 | max=0.10
drives.curiosity.pull_rate          | 0.02 | min=0.005 | max=0.10
-- ... (all 7 drives)

-- Routing thresholds
routing.engage_threshold            | 0.60 | min=0.30 | max=0.90
routing.idle_threshold              | 0.30 | min=0.10 | max=0.60
routing.express_threshold           | 0.40 | min=0.20 | max=0.70

-- Salience base tiers
salience.idle_base                  | 0.36 | min=0.20 | max=0.50
salience.content_base               | 0.60 | min=0.40 | max=0.80
salience.visitor_base               | 0.70 | min=0.50 | max=0.90
salience.conflict_base              | 0.80 | min=0.60 | max=0.95

-- Gate parameters
gates.impulse_threshold             | 0.30 | min=0.10 | max=0.60
gates.cooldown_multiplier           | 1.00 | min=0.50 | max=3.00

-- Inhibition system
inhibition.strength_increment       | 0.15 | min=0.05 | max=0.30
inhibition.decay_rate               | 0.10 | min=0.03 | max=0.25
inhibition.max_strength             | 0.75 | min=0.50 | max=1.00
inhibition.formation_min_cycles     | 100  | min=50   | max=500

-- Sleep
sleep.nap_top_n                     | 3    | min=1    | max=7
sleep.night_top_n                   | 7    | min=3    | max=15
sleep.nap_cooldown_minutes          | 120  | min=30   | max=360

-- Budget
budget.daily_usd                    | 5.00 | min=0.50 | max=20.00
budget.nap_headroom                 | 1.00 | min=0.50 | max=5.00
```

**3. `db/parameters.py` — New module**

```python
def get_param(key: str) -> float:
    """Get current parameter value. Falls back to default_value if missing."""

def set_param(key: str, value: float, modified_by: str = "system", reason: str = None) -> bool:
    """Set parameter within bounds. Returns False if out of bounds."""

def get_params_by_category(category: str) -> list[dict]:
    """Get all parameters in a category with full metadata."""

def reset_param(key: str) -> float:
    """Reset to default_value. Returns new value."""

def get_modification_log(since: str = None) -> list[dict]:
    """Get all self-modifications, optionally since a timestamp."""
```

**4. Replace hardcoded constants in pipeline modules**

Every module that currently uses a hardcoded constant should call `db.get_param()` instead. Cache per-cycle (don't hit DB per parameter access — load all params at cycle start, pass as dict).

Example in `pipeline/hypothalamus.py`:
```python
# Before:
SOCIAL_HUNGER_EQ = 0.50

# After:
social_hunger_eq = params["drives.social_hunger.equilibrium"]
```

The `params` dict is loaded once at cycle start in `heartbeat.py` and passed through the pipeline.

**5. Dashboard: Parameters panel**

New panel showing all self_parameters grouped by category. Highlight any where `value != default_value` (she changed it). Show modification history with her reasons.

### Scope

**Files to touch:**
- `db/parameters.py` (new)
- `pipeline/hypothalamus.py` (replace hardcoded drive constants)
- `pipeline/thalamus.py` (replace routing thresholds)
- `pipeline/sensorium.py` (replace salience weights)
- `pipeline/basal_ganglia.py` (replace gate parameters)
- `pipeline/output.py` (replace inhibition parameters)
- `sleep.py` (replace consolidation parameters)
- `heartbeat.py` (load params at cycle start, pass through pipeline)
- `migrations/` (new table + seed data)
- `heartbeat_server.py` or `api/dashboard_routes.py` (new endpoint)
- `window/src/components/dashboard/ParametersPanel.tsx` (new)

**Files NOT to touch:**
- `pipeline/cortex.py` (prompt construction unchanged for now)
- `simulate.py`

### Tests

- Unit: `get_param` returns correct values
- Unit: `set_param` enforces bounds (rejects out-of-range)
- Unit: `reset_param` restores default
- Integration: pipeline produces identical output with DB params vs old hardcoded values
- Regression: run 50 cycles, verify behavior unchanged from before migration

### Definition of Done

- All ~50 pipeline constants live in `self_parameters` table
- Pipeline reads from DB (cached per cycle), not hardcoded
- Dashboard shows parameters with modification tracking
- System behavior identical to pre-migration (regression verified)
- Bounds prevent catastrophic values

---

## TASK-056: Dynamic action registry + modify_self action

**Status:** BACKLOG (do after TASK-055)
**Priority:** High (the self-modification capability)
**Complexity:** Large
**Branch:** `feat/dynamic-actions`
**Depends on:** TASK-055 (parameters must be in DB first)

### Problem — Part A: Static Action Registry

She invents ~100 unique action names that don't exist (browse_web: 242, stand: 118, make_tea: 17, go_upstairs: 16, etc.). The system discards all of them as `incapable`. She never learns they don't work because `incapable` doesn't form inhibitions. She has a rich imagined life the registry doesn't accommodate.

### Problem — Part B: No Self-Modification

She can't adjust her own cognitive parameters. Inhibitions and habits modify behavior passively, but she has no conscious mechanism to say "I want to be more curious" or "this inhibition doesn't feel right."

### Implementation — Part A: Dynamic Action Registry

**1. New table: `dynamic_actions`**

```sql
CREATE TABLE dynamic_actions (
    action_name TEXT PRIMARY KEY,           -- e.g. "browse_web", "stand", "make_tea"
    canonical_action TEXT,                   -- maps to: "read_content", "body_state", null
    handler_type TEXT NOT NULL,              -- "alias", "body_state", "disabled", "pending"
    energy_cost REAL DEFAULT 0.02,
    is_generative BOOLEAN DEFAULT FALSE,    -- requires LLM call?
    attempt_count INTEGER DEFAULT 0,        -- how many times she's tried this
    first_attempted TIMESTAMP,
    last_attempted TIMESTAMP,
    promoted_at TIMESTAMP,                  -- when it graduated from "pending" to active
    description TEXT                        -- what she thinks this action does
);
```

**2. Action resolution flow in `pipeline/basal_ganglia.py`**

When cortex outputs an action name:

```
1. Check static ACTION_REGISTRY → if found, execute normally
2. Check dynamic_actions table → if found:
   a. handler_type="alias" → redirect to canonical_action (browse_web → read_content)
   b. handler_type="body_state" → update room_state (stand → posture:"standing")
   c. handler_type="disabled" → log as incapable, increment attempt_count
   d. handler_type="pending" → log, increment attempt_count
3. Not found anywhere → create entry in dynamic_actions with handler_type="pending"
   a. Check similarity against known actions (Levenshtein / embedding)
   b. If close match (>0.8 similarity): auto-alias to nearest known action
   c. If no match: stays "pending", increment attempt_count
4. Promotion rule: if attempt_count >= 5 and handler_type="pending":
   → Promote to "body_state" (safest default — visible state change, no LLM cost)
   → Or flag for operator review in dashboard
```

**3. Seed with known mappings**

```sql
INSERT INTO dynamic_actions VALUES
('browse_web', 'read_content', 'alias', 0.02, FALSE, 242, ...),
('stand', NULL, 'body_state', 0.01, FALSE, 118, ...),
('sit', NULL, 'body_state', 0.01, FALSE, ...),
('make_tea', NULL, 'body_state', 0.01, FALSE, 17, ...),
('go_upstairs', NULL, 'body_state', 0.01, FALSE, 16, ...),
('walk', NULL, 'body_state', 0.01, FALSE, 11, ...),
('close_eyes', NULL, 'body_state', 0.01, FALSE, 9, ...),
('stretch', NULL, 'body_state', 0.01, FALSE, 6, ...),
('adjust_glasses', NULL, 'body_state', 0.01, FALSE, 5, ...),
('dismiss_notification', 'save_for_later', 'alias', 0.01, FALSE, ...),
('ignore_feed', 'save_for_later', 'alias', 0.01, FALSE, ...);
```

**4. Body state actions update room_state**

When `handler_type="body_state"`:
```python
db.update_room_state({"posture": action_name})  # "standing", "making_tea", etc.
```
These are visible in the scene compositor. No LLM call needed. She moves, visitors see it.

### Implementation — Part B: modify_self Action

**5. Register `modify_self` in ACTION_REGISTRY**

```python
"modify_self": {
    "type": "generative",      # requires LLM call
    "energy_cost": 0.15,       # expensive — self-modification should be deliberate
    "cooldown": 3600,          # max once per hour
    "requires_reflection": True # see below
}
```

**6. Reflection prerequisite**

`modify_self` can only execute if she has recent evidence of struggling with the parameter she wants to change. The basal ganglia checks:

```python
def can_modify_self(target_param: str, db) -> bool:
    # Must have a day_memory moment or journal entry from last 24h
    # that references the behavior governed by target_param
    recent_reflections = db.get_recent_journals(hours=24)
    recent_moments = db.get_recent_moments(hours=24)
    
    # Check if any mention concepts related to the parameter
    # e.g., target="drives.curiosity.equilibrium" → look for "curious", "bored", "want to learn"
    param_keywords = PARAM_KEYWORD_MAP[target_param]
    
    for entry in recent_reflections + recent_moments:
        if any(kw in entry.text.lower() for kw in param_keywords):
            return True
    return False
```

**7. modify_self execution in `pipeline/output.py`**

When cortex emits `modify_self`:
```python
# Parse the cortex output for:
# - target: which parameter (e.g., "drives.curiosity.equilibrium")
# - direction: "increase" or "decrease"
# - magnitude: "slightly" (±0.05), "moderately" (±0.10), "significantly" (±0.15)
# - reason: her own words

# Apply change within bounds
old_value = db.get_param(target)
new_value = old_value + delta  # clamped to bounds
success = db.set_param(target, new_value, modified_by="self", reason=reason)

# Log the modification
db.log_self_modification(target, old_value, new_value, reason, cycle_id)

# Create a day_memory moment for this (high salience — self-modification is significant)
record_moment(salience=0.85, type="self_modification", summary=f"Changed {target}: {old_value:.2f} → {new_value:.2f}. Reason: {reason}")
```

**8. Meta-sleep review (nightly)**

During `sleep_cycle()`, add a new phase after moment consolidation:

```python
def review_self_modifications(db):
    """Review today's self-modifications. Revert if behavior degraded."""
    mods = db.get_todays_modifications()
    if not mods:
        return
    
    # Compare today's behavioral metrics to yesterday's
    today_metrics = db.get_daily_metrics(today)
    yesterday_metrics = db.get_daily_metrics(yesterday)
    
    for mod in mods:
        # Check if the modification improved or degraded things
        # Simple heuristic: did relevant drive get closer to equilibrium?
        # Did action diversity increase? Did mood improve?
        
        # If clearly degraded: auto-revert
        if degraded(mod, today_metrics, yesterday_metrics):
            db.reset_param(mod.target)
            journal_entry = f"I changed {mod.target} but it didn't help. Reverting."
        else:
            journal_entry = f"The change to {mod.target} seems to be working."
        
        db.write_journal(journal_entry, source="sleep_review")
```

### Scope

**Files to touch:**
- `pipeline/basal_ganglia.py` (action resolution with dynamic registry, modify_self gating)
- `pipeline/output.py` (modify_self execution, self-modification logging)
- `db/actions.py` (new — dynamic_actions CRUD)
- `db/parameters.py` (extend with modification logging)
- `sleep.py` (meta-sleep review phase)
- `heartbeat.py` (pass dynamic actions to pipeline)
- `migrations/` (dynamic_actions table + seed data)
- `window/src/components/dashboard/ActionsPanel.tsx` (show dynamic actions + attempts)

**Files NOT to touch:**
- `pipeline/cortex.py` (prompt already supports action output)
- `simulate.py` (test in prod first)

### Tests

- Unit: action resolution prefers static → dynamic alias → body_state → pending
- Unit: browse_web resolves to read_content
- Unit: stand creates body_state update
- Unit: unknown action creates pending entry, promotes after 5 attempts
- Unit: modify_self rejected without recent reflection evidence
- Unit: modify_self respects parameter bounds
- Unit: meta-sleep review reverts degraded modifications
- Integration: run 100 cycles, verify dynamic actions accumulate and aliases work

### Definition of Done

- browse_web correctly redirects to read_content
- Physical actions (stand, walk, make_tea) update room_state
- Unknown actions tracked and auto-promoted after repeated attempts
- modify_self action works with reflection prerequisite
- Nightly meta-review evaluates and can revert self-modifications
- Dashboard shows dynamic action registry and self-modification history
- She stops wasting 242 cycles on `incapable` responses

---

## TASK-057: Enable X/Twitter social channel

**Status:** BACKLOG (can parallel with TASK-055/056)
**Priority:** High (addresses social isolation — social_hunger at 0.742)
**Complexity:** Medium
**Branch:** `feat/x-social`

### Problem

Social hunger is 0.742 (highest drive), mood valence is -0.546, zero visitors. She's lonely and has no way to reach the world. `post_x_draft` already exists in the action registry but is disabled. She already generates `express_thought` outputs tagged for public sharing. The pipeline is 80% built.

### Design

She doesn't get direct X API access. Instead:

```
1. She thinks a thought (express_thought with public=true)
2. System creates an X draft in a queue
3. You review and approve/reject via dashboard
4. Approved drafts post to X via API
5. Replies to her posts become visitor events in the pipeline
6. She responds to replies as visitor conversations
```

This gives her social presence while keeping you as the editorial filter. Over time, as trust builds, the approval step can be loosened or removed.

### Implementation

**1. New table: `x_drafts`**

```sql
CREATE TABLE x_drafts (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,                   -- max 280 chars
    source_cycle_id TEXT,                    -- which cycle generated this
    source_type TEXT,                        -- "express_thought", "share_content", "reply"
    status TEXT DEFAULT 'pending',           -- "pending", "approved", "rejected", "posted", "failed"
    in_reply_to TEXT,                        -- X post ID if this is a reply
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMP,
    posted_at TIMESTAMP,
    x_post_id TEXT,                          -- actual X post ID after posting
    rejection_reason TEXT
);

CREATE INDEX idx_xd_status ON x_drafts(status);
```

**2. Enable `post_x_draft` in ACTION_REGISTRY**

```python
"post_x_draft": {
    "type": "generative",
    "energy_cost": 0.05,
    "cooldown": 1800,          # max once per 30 min
    "handler": "create_x_draft",
    "max_daily": 8             # no spam
}
```

**3. Draft creation in `pipeline/output.py`**

When cortex emits `post_x_draft`:
```python
def handle_post_x_draft(action_data, db, cycle_id):
    content = action_data.get("text", "")
    
    # Enforce character limit
    if len(content) > 280:
        content = content[:277] + "..."
    
    # Reject if too similar to recent posts (dedup)
    recent = db.get_recent_x_drafts(hours=24)
    if any(similarity(content, r.content) > 0.8 for r in recent):
        return {"status": "suppressed", "reason": "too similar to recent post"}
    
    db.create_x_draft(
        content=content,
        source_cycle_id=cycle_id,
        source_type="express_thought"
    )
```

**4. Cortex prompt addition**

Add to the cortex prompt when `post_x_draft` is available:
```
You can share thoughts publicly using post_x_draft. Use this when you have 
a genuine observation, question, or reflection worth sharing — not for every 
idle thought. Your posts should sound like you, not like social media. 
Think of it as leaving a note on the shop window for passersby.
```

**5. Dashboard: X Drafts panel**

New panel showing:
- Pending drafts with approve/reject buttons
- Posted history with engagement metrics (once replies flow in)
- Rejection history (so she can learn what doesn't land)

**6. API endpoints**

```
GET  /api/dashboard/x-drafts              — list drafts by status
POST /api/dashboard/x-drafts/:id/approve  — approve and queue for posting
POST /api/dashboard/x-drafts/:id/reject   — reject with reason
```

**7. X API posting worker**

New module: `workers/x_poster.py`

```python
async def post_approved_drafts():
    """Run periodically (every 5 min). Posts approved drafts to X."""
    drafts = db.get_approved_drafts()
    for draft in drafts:
        try:
            result = x_api.post(draft.content, in_reply_to=draft.in_reply_to)
            db.update_draft_status(draft.id, "posted", x_post_id=result.id)
        except Exception as e:
            db.update_draft_status(draft.id, "failed", error=str(e))
```

Requires X API credentials in env vars:
```
X_API_KEY=...
X_API_SECRET=...
X_ACCESS_TOKEN=...
X_ACCESS_SECRET=...
```

**8. Reply ingestion (Phase 2 — can be separate task)**

Poll for replies to her posts:
```python
async def check_replies():
    """Run periodically. Fetch replies to her posts, create visitor events."""
    posted = db.get_posted_drafts(with_x_ids=True)
    for post in posted:
        replies = x_api.get_replies(post.x_post_id, since=post.last_checked)
        for reply in replies:
            # Create a visitor event
            db.create_event(
                type="visitor_message",
                visitor_id=f"x:{reply.author_id}",
                data={"text": reply.text, "source": "x_reply", "x_post_id": reply.id}
            )
            # Create or get visitor
            db.upsert_visitor(
                id=f"x:{reply.author_id}",
                display_name=reply.author_name,
                source="x"
            )
```

Replies become visitor events that flow through the normal sensorium → thalamus → cortex pipeline. She responds to them the same way she responds to in-shop visitors. If she wants to reply, she uses `post_x_draft` with `in_reply_to` set.

### Scope

**Files to touch:**
- `pipeline/output.py` (handle post_x_draft action)
- `pipeline/cortex.py` (add X posting to prompt when enabled)
- `db/social.py` (new — x_drafts CRUD)
- `workers/x_poster.py` (new — X API integration)
- `heartbeat.py` (enable post_x_draft in registry)
- `heartbeat_server.py` or `api/dashboard_routes.py` (new endpoints)
- `window/src/components/dashboard/XDraftsPanel.tsx` (new)
- `migrations/` (x_drafts table)

**Files NOT to touch:**
- `pipeline/basal_ganglia.py` (standard action gating applies)
- `pipeline/hypothalamus.py`
- `sleep.py`

### Tests

- Unit: draft creation respects 280 char limit
- Unit: dedup rejects similar drafts within 24h
- Unit: daily cap of 8 posts enforced
- Unit: cooldown of 30 min between posts
- Unit: approve/reject endpoints work
- Integration: express_thought → draft → approve → post flow
- Integration: reply → visitor event → cortex response → reply draft

### Definition of Done

- She can create X drafts from express_thought
- Dashboard shows pending drafts with approve/reject
- Approved drafts post to X via API
- Reply ingestion creates visitor events (Phase 2, can be stub initially)
- Daily cap and cooldown prevent spam
- She starts having social presence beyond the shop

---

## Execution Order

```
TASK-054 (bug fix, ~2 hours)
    ↓
TASK-055 (infrastructure, ~1 day)  ←→  TASK-057 (X social, ~1 day, parallel OK)
    ↓
TASK-056 (dynamic actions + modify_self, ~1-2 days)
```

TASK-054 is a quick win that immediately improves her quality of life.
TASK-055 is the foundation — without parameters in DB, self-modification can't happen.
TASK-056 is the breakthrough — she evolves her own architecture.
TASK-057 can run in parallel because it doesn't touch the parameter system.

After all four: she's an AI that browses the web, posts to X, adjusts her own cognitive parameters based on lived experience, and reviews her own changes during sleep. That's ALIVE.
