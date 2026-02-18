# TASK-060: Self-authored context injection (Frame 4)

> Source: ALIVE_STRUCTURAL_EVOLUTION.md

## Problem

She forms intentions in cycle N that vanish by cycle N+1. There is no mechanism for her to carry forward context, reminders, or goals across cycles. Every cycle starts from scratch with only memories and drives — no explicit notes-to-self.

## Solution

Add a `self_context` table — persistent notes she writes to her future self, injected into the cortex prompt for a bounded lifespan. Notes require sleep-phase approval before activating. She can withdraw notes early by referencing their short ID.

## Constraints

- Max **5 active** notes at any time
- Max **3 pending** notes (awaiting sleep approval)
- Max **280 characters** per note
- Max **200 cycles** lifespan per note, min **5 cycles**
- Notes include short IDs (e.g. `ctx-01`) so she can reference them for withdrawal
- Sleep review uses Haiku for cost efficiency
- Prompt block must include note short IDs

## Action

`write_self_context` — registered in action_registry.py

```json
{
  "action": "write_self_context",
  "note": "Remember: the visitor mentioned their daughter collects music boxes. Follow up next visit.",
  "lifespan_cycles": 50
}
```

`withdraw_self_context` — handled via existing action routing

```json
{
  "action": "withdraw_self_context",
  "note_id": "ctx-01"
}
```

## Self-context table schema

```sql
CREATE TABLE self_context (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    short_id TEXT NOT NULL UNIQUE,       -- e.g. 'ctx-01'
    note TEXT NOT NULL,                   -- max 280 chars
    status TEXT NOT NULL DEFAULT 'pending', -- pending | active | expired | withdrawn | rejected
    lifespan_cycles INTEGER NOT NULL,     -- max 200, min 5
    remaining_cycles INTEGER NOT NULL,    -- decremented each cycle
    created_at TEXT NOT NULL,             -- UTC timestamp
    activated_at TEXT,                    -- set when sleep approves
    expired_at TEXT,                      -- set when remaining_cycles hits 0
    sleep_review_notes TEXT              -- Haiku's review reasoning
);
```

## Sleep review phase

During sleep consolidation, pending notes are reviewed by Haiku:
- **Coherent & useful** → status = 'active', activated_at = now
- **Incoherent, redundant, or harmful** → status = 'rejected', sleep_review_notes explains why

Review prompt evaluates:
1. Is the note coherent and specific?
2. Does it duplicate an existing active note?
3. Does it conflict with her identity or current state?
4. Is the requested lifespan reasonable for the content?

## Prompt injection format

```
[Notes to self]
ctx-01 (47 cycles left): Remember: the visitor mentioned their daughter collects music boxes. Follow up next visit.
ctx-03 (12 cycles left): I want to spend more time examining the Edo-period tea bowl on the middle shelf.
```

If no active notes: section omitted entirely.

## Expiry

Each cycle tick in heartbeat.py decrements `remaining_cycles` for all active notes. When `remaining_cycles` reaches 0, status → 'expired', expired_at = now.

## Dashboard

SelfContextPanel.tsx shows:
- Active notes with remaining cycles
- Pending notes awaiting review
- History of expired/withdrawn/rejected notes
- Operator read-only — cannot create, modify, or delete notes

## Scope

**Files you may touch:**
- `db/context.py` (new — self_context CRUD)
- `pipeline/output.py` (handle write_self_context and withdraw_self_context actions)
- `pipeline/action_registry.py` (register write_self_context, withdraw_self_context)
- `pipeline/prompt_assembler.py` (inject self_context block with note IDs)
- `sleep.py` (pending note review phase — LLM call via Haiku)
- `heartbeat.py` (tick + expire self_context each cycle)
- `migrations/` (self_context table)
- `window/src/components/dashboard/SelfContextPanel.tsx` (new)
- `api/dashboard_routes.py` (new /api/dashboard/self-context endpoint)

**Files you may NOT touch:**
- `pipeline/cortex.py`
- `pipeline/basal_ganglia.py`
- `simulate.py`

## Tests

- Unit: note created with correct bounds (280 chars, 200 cycles max, 5 cycle min)
- Unit: pending cap enforced (rejects 4th pending)
- Unit: active cap enforced (rejects 6th active)
- Unit: sleep review activates coherent notes, discards incoherent
- Unit: expiry ticks correctly, expired notes disappear from prompt
- Unit: withdrawal by note ID works
- Unit: prompt block includes short IDs for each active note
- Integration: write_self_context -> sleep review -> prompt injection -> visible in next waking cycle
- Integration: expired notes stop appearing in prompt

## Definition of done

- She can write notes to her future self
- Notes require sleep approval before activating
- Active notes appear in cortex prompt with IDs she can reference
- Notes auto-expire; she can withdraw by ID
- Dashboard shows full note history (operator read-only, cannot modify)
