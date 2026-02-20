# TASK-056 Implementation Plan: Dynamic Action Registry + modify_self Action

> **Status:** BACKLOG → needs READY
> **Depends on:** TASK-055 (DONE)
> **Branch:** `feat/dynamic-actions`
> **Estimated phases:** 6 (can chain 2-3 per session)

---

## Phase 0: Documentation & Reference Summary

### Allowed APIs (verified from source)

**db/parameters.py** (lines 22-181):
- `refresh_params_cache()` — load all params into `_cache` per cycle
- `p(key)` / `p_or(key, default)` — sync cache reads
- `set_param(key, value, modified_by, reason)` — write with bounds enforcement + audit log
- `reset_param(key, modified_by)` — reset to default_value
- `get_modification_log(key, limit)` — audit trail

**pipeline/action_registry.py** (lines 52-244):
- `ActionCapability` dataclass: `name, enabled, cooldown_seconds, last_used, max_per_cycle, requires, description, generative`
- `ACTION_REGISTRY` — static dict, ~21 entries (15 enabled, 6 disabled)
- `check_prerequisites(requires, context)` → `PrereqResult(passed, failed)`

**pipeline/basal_ganglia.py** (lines 293-424):
- `select_actions(validated, drives, context)` → `MotorPlan`
- Gate sequence: Registry lookup → enabled → prerequisites → cooldown → shop gate → drive gate → inhibition
- Unknown actions get `status='incapable'`, reason `'Unknown action: {name}'`
- Imports `ACTION_REGISTRY` at module level (line 26)

**pipeline/body.py** (lines 34-326):
- `execute_body(motor_plan, validated, visitor_id, cycle_id)` → `BodyOutput`
- `_execute_single_action(action_req, visitor_id, monologue)` — flat if-elif dispatch
- No modify_self handler currently exists

**pipeline/output.py** (lines 84-1109):
- `process_output(body_output, validated, visitor_id, motor_plan, cycle_id)` → `CycleOutput`
- Drive adjustments at lines 146-213
- Action logging via `_log_motor_plan()` (line 358)
- No parameter modification currently

**sleep.py** (lines 24-400+):
- `sleep_cycle()` — 9 sequential phases
- Trait stability review at line 122
- Best insertion for meta-sleep: between line 122 (trait review) and line 125 (thread lifecycle)
- `reset_drives_for_morning()` at line 131

**heartbeat.py**:
- `run_cycle()` calls `select_actions(validated, drives, context=bg_context)` at line 1158
- `bg_context = { visitor_present, turn_count, mode, cycle_type }`
- ACTION_REGISTRY imported in `__init__` at line 187 to set post_x cooldown

**db/connection.py** (lines 378-427):
- `run_migrations(conn)` — reads `migrations/` dir, executes `.sql` files by version number
- Highest migration: `022_self_parameters.sql`

**Dashboard patterns** (verified from ParametersPanel.tsx + dashboard_routes.py):
- Component: React hooks, useCallback fetch, 15s polling, category-grouped display
- API: handler functions in `api/dashboard_routes.py`, routed from `heartbeat_server.py`
- Client: `dashboardApi.*` functions in `window/src/lib/dashboard-api.ts`

### Anti-Patterns to Avoid
- Do NOT modify `pipeline/cortex.py` or `simulate.py` (explicitly out of scope)
- Do NOT add direct DB calls outside `db/` modules
- Do NOT change `ACTION_REGISTRY` from dict to DB-loaded per-cycle (too invasive) — instead, augment with a dynamic overlay
- Do NOT allow modify_self to change identity/voice parameters (only cognitive tuning)
- Do NOT use `time.time()` or `datetime.now()` — use `clock.now()` / `clock.now_utc()`

---

## Phase 1: Migration + Dynamic Actions DB Layer

**Goal:** Create the `dynamic_actions` table and `db/actions.py` CRUD module.

### Files to create/modify:
- **CREATE** `migrations/023_dynamic_actions.sql`
- **CREATE** `db/actions.py`
- **MODIFY** `db/__init__.py` (add exports)

### Step 1.1: Migration `023_dynamic_actions.sql`

```sql
CREATE TABLE IF NOT EXISTS dynamic_actions (
    action_name   TEXT PRIMARY KEY,
    alias_for     TEXT,          -- NULL if not an alias; points to static action name
    body_state    TEXT,          -- NULL if not a body-state action; JSON body state update
    status        TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'alias' | 'body_state' | 'promoted' | 'rejected'
    attempt_count INTEGER NOT NULL DEFAULT 1,
    promote_threshold INTEGER NOT NULL DEFAULT 5,
    first_seen    TEXT NOT NULL, -- ISO UTC timestamp
    last_seen     TEXT NOT NULL, -- ISO UTC timestamp
    resolved_by   TEXT,          -- 'auto' | 'operator' | 'sleep_review'
    notes         TEXT
);

-- Seed known aliases (browse_web → read_content, etc.)
-- Column list must include body_state to populate it correctly
INSERT OR IGNORE INTO dynamic_actions (action_name, alias_for, body_state, status, attempt_count, first_seen, last_seen, resolved_by)
VALUES
    ('browse_web', 'read_content', NULL,                        'alias',      242, datetime('now'), datetime('now'), 'seed'),
    ('stand',      NULL,           '{"body_state":"standing"}', 'body_state', 118, datetime('now'), datetime('now'), 'seed'),
    ('sit',        NULL,           '{"body_state":"sitting"}',  'body_state',  50, datetime('now'), datetime('now'), 'seed'),
    ('make_tea',   NULL,           NULL,                        'pending',     17, datetime('now'), datetime('now'), NULL);
```

> **Note:** The seed data above shows the pattern. Actual seed values should include the top ~20 "incapable" actions from production logs. The exact list comes from the task description (browse_web: 242, stand: 118, make_tea: 17).

### Step 1.2: `db/actions.py`

Create the CRUD module following the pattern of `db/parameters.py`:

```python
# Functions to implement:
async def get_dynamic_action(action_name: str) -> dict | None
async def get_all_dynamic_actions() -> list[dict]
async def get_dynamic_actions_by_status(status: str) -> list[dict]
async def record_unknown_action(action_name: str) -> dict
    # If exists: increment attempt_count, update last_seen
    # If new: INSERT with status='pending', attempt_count=1
async def resolve_action(action_name: str, status: str, alias_for: str = None,
                         body_state: str = None, resolved_by: str = 'operator') -> dict
async def promote_pending_actions(threshold: int = 5) -> list[dict]
    # Auto-promote actions with attempt_count >= threshold
async def get_action_stats() -> dict
    # Summary: total, by status, top pending
```

### Step 1.3: Export from `db/__init__.py`

Add to the imports section (following the existing pattern at bottom of file):
```python
from db.actions import (
    get_dynamic_action, get_all_dynamic_actions, get_dynamic_actions_by_status,
    record_unknown_action, resolve_action, promote_pending_actions, get_action_stats,
)
```

### Verification:
- [ ] `python -c "import db; print(db.get_dynamic_action)"` — no import error
- [ ] Migration applies: `python -c "import asyncio; from db.connection import init_db; asyncio.run(init_db())"` creates table
- [ ] `gtimeout 60 python3 -m pytest tests/test_db_actions.py -v --tb=short 2>&1 || true` (write basic tests)

---

## Phase 2: Dynamic Resolution in Basal Ganglia

**Goal:** Replace the binary "in registry or incapable" check with a 4-tier resolution: static registry → dynamic alias → body_state → pending.

### Files to modify:
- **MODIFY** `pipeline/basal_ganglia.py` (Gate 1 rewrite)
- **CREATE** `tests/test_dynamic_actions.py`

### ⚠️ Async ripple warning
`select_actions()` is currently a regular `async def` but `_resolve_dynamic_action()` adds a DB await inside the gate loop. Verify that `select_actions` is already declared `async def` (it is — line 293 in basal_ganglia.py). The call site in `heartbeat.py` (line 1158) already uses `await select_actions(...)` so **no change needed there**. If `check_habits()` is called without await anywhere, double-check those call sites too.

### Step 2.1: Rewrite Gate 1 in `select_actions()` (basal_ganglia.py ~lines 329-333)

**Current code (lines 329-333):**
```python
if action_name not in ACTION_REGISTRY:
    decision.status = 'incapable'
    decision.suppression_reason = f'Unknown action: {action_name}'
    decisions.append(decision)
    continue
```

**New code (replace the above block):**
```python
# Gate 1: Action resolution — static → dynamic alias → body_state → pending
if action_name not in ACTION_REGISTRY:
    resolved = await _resolve_dynamic_action(action_name, decision)
    if resolved is None:
        # Truly unknown — record as pending, mark incapable
        decisions.append(decision)
        continue
    elif resolved == 'alias':
        # Swap action_name to the alias target, continue through gates
        action_name = decision.action  # updated by _resolve_dynamic_action
    elif resolved == 'body_state':
        # Body state update — auto-approve, skip remaining gates
        decisions.append(decision)
        continue
```

### Step 2.2: Add `_resolve_dynamic_action()` helper (new function in basal_ganglia.py)

```python
async def _resolve_dynamic_action(action_name: str, decision: ActionDecision) -> str | None:
    """Resolve an unknown action via the dynamic actions table.

    Returns:
        'alias' — action was an alias, decision.action updated to target
        'body_state' — action is a body state update, decision auto-approved
        None — action recorded as pending, decision marked incapable
    """
    import db  # local import to avoid circular

    dyn = await db.get_dynamic_action(action_name)

    if dyn is None:
        # Never seen before — record it
        await db.record_unknown_action(action_name)
        decision.status = 'incapable'
        decision.suppression_reason = f'Unknown action: {action_name} (recorded as pending)'
        return None

    if dyn['status'] == 'alias' and dyn['alias_for']:
        # Redirect to the aliased action
        target = dyn['alias_for']
        if target in ACTION_REGISTRY and ACTION_REGISTRY[target].enabled:
            decision.action = target
            decision.detail['_original_action'] = action_name
            return 'alias'
        else:
            decision.status = 'incapable'
            decision.suppression_reason = f'Alias {action_name}→{target} but target disabled'
            return None

    if dyn['status'] == 'body_state' and dyn['body_state']:
        # Auto-approve as body state change
        decision.status = 'approved'
        decision.detail['_body_state_update'] = dyn['body_state']
        decision.detail['_original_action'] = action_name
        return 'body_state'

    # Pending or rejected — increment count, stay incapable
    await db.record_unknown_action(action_name)  # bumps attempt_count
    decision.status = 'incapable'
    decision.suppression_reason = f'Unknown action: {action_name} (seen {dyn["attempt_count"] + 1}x, pending review)'
    return None
```

### Step 2.3: Handle body_state actions in body.py

Add a new elif branch in `_execute_single_action()` (body.py, after the last elif):

```python
# Dynamic body state actions (from dynamic_actions table)
elif '_body_state_update' in action.detail:
    import json
    state_update = json.loads(action.detail['_body_state_update'])
    if 'body_state' in state_update:
        validated.body_state = state_update['body_state']
    await db.append_event(Event(
        event_type='action_body',
        content=f'Dynamic body action: {action.detail.get("_original_action", action.type)}',
        payload=state_update,
    ))
    result.success = True
```

### Verification:
- [ ] Test: `browse_web` resolves to `read_content` (alias)
- [ ] Test: `stand` creates body_state update
- [ ] Test: `fly_to_moon` creates pending entry
- [ ] Test: pending action with 5+ attempts stays incapable (no auto-promote in this phase)
- [ ] Test: unknown action increments attempt_count on repeat
- [ ] `gtimeout 120 python3 -m pytest tests/ --tb=short -q 2>&1 || true` — full suite passes

---

## Phase 3: modify_self Action (Gated Behind Reflection)

**Goal:** Add the `modify_self` action that allows the Shopkeeper to adjust her own cognitive parameters, gated behind evidence of recent reflection.

### Files to modify:
- **MODIFY** `pipeline/action_registry.py` (add modify_self to ACTION_REGISTRY)
- **MODIFY** `pipeline/basal_ganglia.py` (add reflection-evidence gate for modify_self)
- **MODIFY** `pipeline/body.py` (add modify_self execution)
- **MODIFY** `pipeline/output.py` (add modify_self logging/side-effects)
- **MODIFY** `db/parameters.py` (extend if needed for modify_self modified_by tracking)

### Step 3.1: Register modify_self in ACTION_REGISTRY (action_registry.py)

Add after the last enabled action (~line 191):

```python
'modify_self': ActionCapability(
    name='modify_self',
    enabled=True,
    cooldown_seconds=300,  # 5 min between self-modifications
    max_per_cycle=1,
    requires=[],  # Custom gate in basal_ganglia, not standard prereqs
    description='Adjust a cognitive parameter based on reflection evidence',
    generative=False,
),
```

### Step 3.2: Reflection-evidence gate in basal_ganglia.py

Add a new gate check after Gate 6 (inhibition), specifically for modify_self:

```python
# Gate 7: modify_self requires recent reflection evidence
if action_name == 'modify_self':
    has_evidence = await _has_reflection_evidence()
    if not has_evidence:
        decision.status = 'suppressed'
        decision.suppression_reason = 'modify_self requires recent reflection (journal/monologue within last 3 cycles)'
        decisions.append(decision)
        continue
    # Validate parameter key and bounds
    param_key = decision.detail.get('parameter')
    new_value = decision.detail.get('value')
    if not param_key or new_value is None:
        decision.status = 'suppressed'
        decision.suppression_reason = 'modify_self requires parameter and value in detail'
        decisions.append(decision)
        continue
```

New helper:
```python
async def _has_reflection_evidence() -> bool:
    """Check if the Shopkeeper has reflected on the relevant parameter area this cycle.

    Requirement: a journal/monologue event must have been EXECUTED in the current cycle
    (not just any recent event — she journals almost every cycle, so recency alone is
    meaningless). We check for action_journal in the current cycle_id.

    ⚠️ TECH DEBT (v1): cycle_id isn't threaded into _has_reflection_evidence yet.
    Interim: require action_journal in the last 3 events (tight window), not 20.
    Tighten before experiment runs: pass cycle_id from select_actions → _has_reflection_evidence
    and require the journal event to match the current cycle.
    """
    import db
    # Tight window: journal must be very recent (last 3 events), not just "today"
    recent = await db.get_recent_events(limit=3)
    for ev in recent:
        if ev.event_type == 'action_journal':
            return True
    return False
```

> **⚠️ TECH DEBT:** The v1 gate (journal in last 3 events) is tighter than limit=20 but still doesn't verify the journal content relates to the parameter being modified. Before the first real experiment run, thread `cycle_id` into this function and require the reflection to have occurred in the same cycle as the modify_self intention.

### Step 3.3: Execute modify_self in body.py

Add elif branch in `_execute_single_action()`:

```python
elif action.type == 'modify_self':
    from db.parameters import set_param, get_param
    param_key = action.detail.get('parameter', '')
    new_value = action.detail.get('value')
    reason = action.detail.get('reason', 'self-modification')
    try:
        old = await get_param(param_key)
        if old is None:
            result.success = False
            result.error = f'Unknown parameter: {param_key}'
        else:
            await set_param(param_key, float(new_value),
                           modified_by='self', reason=reason)
            result.success = True
            result.detail = {
                'parameter': param_key,
                'old_value': old['value'],
                'new_value': float(new_value),
                'reason': reason,
            }
            await db.append_event(Event(
                event_type='action_modify_self',
                content=f'Modified {param_key}: {old["value"]} → {new_value}',
                payload=result.detail,
            ))
    except ValueError as e:
        result.success = False
        result.error = str(e)  # bounds violation
```

### Step 3.4: Log modify_self side-effects in output.py

In `_log_motor_plan()` or in the main `process_output()` flow, add tracking for self-modifications:

```python
# After action logging section (~line 270)
# Track self-modifications for meta-sleep review
for action_result in body_output.executed:
    if action_result.action == 'modify_self' and action_result.success:
        # The parameter modification is already logged in parameter_modifications table
        # Just emit a high-salience event for the Shopkeeper's awareness
        print(f"  [Output] Self-modification: {action_result.detail}")
```

### Verification:
- [ ] Test: modify_self rejected without recent reflection evidence
- [ ] Test: modify_self rejected with missing parameter/value
- [ ] Test: modify_self respects parameter bounds (set_param raises ValueError)
- [ ] Test: modify_self succeeds with valid params + reflection evidence
- [ ] Test: modify_self event logged with correct payload
- [ ] Test: modify_self cooldown enforced (300s)
- [ ] `gtimeout 120 python3 -m pytest tests/ --tb=short -q 2>&1 || true`

---

## Phase 4: Meta-Sleep Review (Revert Degraded Modifications)

**Goal:** During nightly sleep, review all self-modifications from the day. Revert any that degraded the Shopkeeper's wellbeing metrics.

### Files to modify:
- **MODIFY** `sleep.py` (add meta-sleep review phase)
- **MODIFY** `db/parameters.py` (add helper for day's modifications)

### Step 4.1: Add `get_todays_self_modifications()` to `db/parameters.py`

```python
async def get_todays_self_modifications() -> list[dict]:
    """Get all self-initiated parameter modifications from today."""
    db = await _connection.get_db()
    today_start = clock.now_utc().replace(hour=0, minute=0, second=0).isoformat()
    cursor = await db.execute(
        "SELECT * FROM parameter_modifications "
        "WHERE modified_by = 'self' AND ts >= ? ORDER BY ts ASC",
        (today_start,)
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]
```

### Step 4.2: Add meta-sleep review in `sleep.py`

Insert after `await review_trait_stability()` (line 122):

```python
# ── Phase 5b: Meta-sleep parameter review ──
await review_self_modifications()
```

New function:

```python
# Drive fields governed by each parameter category — used to assess if a modification helped
_CATEGORY_DRIVE_MAP: dict[str, list[str]] = {
    'hypothalamus': ['mood_valence', 'social_hunger', 'curiosity', 'expression_need', 'energy', 'rest_need'],
    'thalamus':     ['curiosity'],
    'sensorium':    ['social_hunger'],
    'basal_ganglia': ['energy'],
    'output':       ['mood_valence', 'mood_arousal'],
    'sleep':        ['rest_need', 'energy'],
}

async def review_self_modifications():
    """Review today's self-modifications. Revert per-parameter if its governed drive degraded.

    Strategy: for each modified parameter, infer which drive(s) it governs from the
    parameter's category prefix. If that drive moved away from equilibrium between
    modification time and now, revert the parameter. General mood is too noisy — a
    lonely night can tank mood_valence regardless of parameter quality.
    """
    from db.parameters import get_todays_self_modifications, reset_param, get_param

    mods = await get_todays_self_modifications()
    if not mods:
        print("  [Sleep] No self-modifications to review")
        return

    print(f"  [Sleep] Reviewing {len(mods)} self-modification(s)")
    drives = await db.get_drives_state()

    for mod in mods:
        param_key = mod['param_key']
        category = param_key.split('.')[0]  # e.g. 'hypothalamus' from 'hypothalamus.equilibria.social_hunger'
        governed_drives = _CATEGORY_DRIVE_MAP.get(category, [])

        # Check if any governed drive moved further from its equilibrium after the mod
        degraded = False
        for drive_field in governed_drives:
            eq_key = f'hypothalamus.equilibria.{drive_field}'
            equilibrium = p_or(eq_key, 0.5)
            current = getattr(drives, drive_field, None)
            old_val = mod['old_value']
            new_val = mod['new_value']
            if current is None:
                continue
            # If current drive is further from equilibrium than a neutral baseline, flag
            deviation = abs(current - equilibrium)
            if deviation > 0.4:  # threshold: more than 0.4 away from equilibrium
                degraded = True
                print(f"    Drive {drive_field} deviation {deviation:.2f} — flagging {param_key} for revert")
                break

        if degraded:
            try:
                await reset_param(param_key, modified_by='meta_sleep_revert')
                print(f"    Reverted: {param_key} ({mod['new_value']} → default)")
            except Exception as e:
                print(f"    Failed to revert {param_key}: {e}")
        else:
            print(f"    Keeping: {param_key} (governed drives within range)")
```

> **⚠️ TECH DEBT:** This v1 heuristic uses end-of-day drive state, not a before/after delta. A better version would snapshot drive values at modification time (store in `parameter_modifications.drive_snapshot JSON`) and compare. The deviation threshold of 0.4 is a guess — tune after first experiment run.

### Verification:
- [ ] Test: review_self_modifications reverts a hypothalamus param when social_hunger deviation > 0.4
- [ ] Test: review_self_modifications keeps modification when governed drives are within range
- [ ] Test: no-op when no self-modifications exist
- [ ] Test: reverted params are logged with modified_by='meta_sleep_revert'
- [ ] `gtimeout 120 python3 -m pytest tests/ --tb=short -q 2>&1 || true`

---

## Phase 5: Heartbeat Integration + Dynamic Action Loading

**Goal:** Wire dynamic actions into the heartbeat cycle so they're available for resolution.

### Files to modify:
- **MODIFY** `heartbeat.py` (load dynamic actions per cycle, pass to pipeline)

### Step 5.1: Load dynamic actions in run_cycle()

After the existing `await db.refresh_params_cache()` call (heartbeat.py ~line 733), add:

```python
# Load dynamic action aliases for this cycle
# (The dynamic_actions table is queried on-demand in basal_ganglia._resolve_dynamic_action,
#  but we can optionally pre-warm a cache here for performance)
```

Actually, since `_resolve_dynamic_action()` in Phase 2 does direct DB queries, and these are lightweight single-row lookups, no pre-warming is needed. The heartbeat integration is minimal:

**The only change needed:** Ensure `bg_context` (line 1149) is passed through correctly — already done in Phase 2.

### Step 5.2: Auto-promote pending actions during sleep

Add to `sleep.py` in the meta-sleep review section:

```python
# Auto-promote high-frequency pending actions
promoted = await db.promote_pending_actions(threshold=5)
if promoted:
    print(f"  [Sleep] Auto-promoted {len(promoted)} pending actions: {[a['action_name'] for a in promoted]}")
```

### Verification:
- [ ] Run a short simulation: `python simulate.py --cycles 10` — verify dynamic actions accumulate
- [ ] Check that browse_web redirects to read_content in live cycle
- [ ] Check that unknown actions create pending entries
- [ ] `gtimeout 120 python3 -m pytest tests/ --tb=short -q 2>&1 || true`

---

## Phase 6: Dashboard Panel + Final Verification

**Goal:** Add ActionsPanel to the dashboard showing the dynamic action registry and modification history.

### Files to create/modify:
- **CREATE** `window/src/components/dashboard/ActionsPanel.tsx`
- **MODIFY** `heartbeat_server.py` or `api/dashboard_routes.py` (add API endpoints)
- **MODIFY** `window/src/lib/dashboard-api.ts` (add client functions)
- **MODIFY** `window/src/lib/types.ts` (add TypeScript types)
- **MODIFY** `window/src/app/dashboard/page.tsx` (add panel)

### Step 6.1: Backend API endpoints

Add to `api/dashboard_routes.py`:

```python
async def handle_actions(server, writer, authorization):
    """GET /api/dashboard/actions — dynamic action registry."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    all_actions = await db.get_all_dynamic_actions()
    stats = await db.get_action_stats()

    await server._http_json(writer, 200, {
        'actions': all_actions,
        'stats': stats,
    })

async def handle_resolve_action(server, writer, authorization, body_bytes):
    """POST /api/dashboard/actions/resolve — resolve a pending action."""
    if not check_dashboard_auth(authorization):
        await server._http_json(writer, 401, {'error': 'unauthorized'})
        return

    data = json.loads(body_bytes.decode('utf-8'))
    result = await db.resolve_action(
        data['action_name'], data['status'],
        alias_for=data.get('alias_for'),
        body_state=data.get('body_state'),
        resolved_by='dashboard',
    )
    await server._http_json(writer, 200, result)
```

Add routes in `heartbeat_server.py`:
```python
elif path == '/api/dashboard/actions' and method == 'GET':
    await dashboard_routes.handle_actions(self, writer, authorization)
elif path == '/api/dashboard/actions/resolve' and method == 'POST':
    await dashboard_routes.handle_resolve_action(self, writer, authorization, body_bytes)
```

### Step 6.2: Frontend types + API client

Add to `types.ts`:
```typescript
export interface DynamicAction {
  action_name: string;
  alias_for: string | null;
  body_state: string | null;
  status: 'pending' | 'alias' | 'body_state' | 'promoted' | 'rejected';
  attempt_count: number;
  first_seen: string;
  last_seen: string;
  resolved_by: string | null;
  notes: string | null;
}
```

Add to `dashboard-api.ts`:
```typescript
async getActions(): Promise<{ actions: DynamicAction[]; stats: Record<string, number> }> {
  const res = await dashboardFetch('/api/dashboard/actions');
  return res.json();
},
async resolveAction(actionName: string, status: string, aliasFor?: string, bodyState?: string) {
  const res = await dashboardFetch('/api/dashboard/actions/resolve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action_name: actionName, status, alias_for: aliasFor, body_state: bodyState }),
  });
  return res.json();
},
```

### Step 6.3: ActionsPanel component

Copy the pattern from `ParametersPanel.tsx`:
- Status-grouped display (pending / alias / body_state / promoted / rejected)
- Pending actions show attempt count + resolve button
- Alias actions show target action
- Recent modification log from parameter_modifications where modified_by='self'
- 15s polling refresh

### Verification:
- [ ] Dashboard loads without errors
- [ ] Actions panel shows seeded data (browse_web, stand, sit, make_tea)
- [ ] Can resolve a pending action via dashboard
- [ ] Parameter modification history shows self-modifications

---

## Final Verification Phase

Run after all phases are complete:

```bash
# Full test suite
gtimeout 120 python3 -m pytest tests/ --tb=short -q 2>&1 || true

# Doc update
python scripts/update_docs.py

# Verify key behaviors
python -c "
import asyncio
from db.connection import init_db
import db

async def check():
    await init_db()
    # Check dynamic action exists
    a = await db.get_dynamic_action('browse_web')
    assert a is not None, 'browse_web not in dynamic_actions'
    assert a['alias_for'] == 'read_content'
    print('OK: browse_web → read_content alias')

    # Check modify_self in registry
    from pipeline.action_registry import ACTION_REGISTRY
    assert 'modify_self' in ACTION_REGISTRY
    assert ACTION_REGISTRY['modify_self'].enabled
    print('OK: modify_self registered and enabled')

asyncio.run(check())
"
```

### Definition of Done checklist:
- [ ] browse_web redirects to read_content
- [ ] Physical actions (stand, sit) update body_state via dynamic resolution
- [ ] Unknown actions tracked and auto-promoted after 5 attempts (during sleep)
- [ ] modify_self works with reflection prerequisite
- [ ] modify_self respects parameter bounds
- [ ] Nightly meta-review evaluates and can revert degraded modifications
- [ ] Dashboard shows registry and modification history
- [ ] All tests pass
- [ ] ARCHITECTURE.md updated via update_docs.py
- [ ] TASKS.md updated: TASK-056 status → DONE
