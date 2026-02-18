# TASK-062: Intra-cycle cognitive loops (Frame 2)

## Problem

Every cycle is a single linear pass through the pipeline. She cannot reflect on her own output, follow up on a question, or deliberate between competing intentions within the same cycle. Complex thought requires iteration.

## Solution

Add three registered loop types (reflection, question, deliberation) that re-enter pipeline subsets within the same heartbeat. Controlled by `cycle.max_llm_calls` parameter and daily LLM call hard cap. She enables/disables loops via `modify_self`.

## Loop types

### Reflection loop
- **Trigger:** `write_journal` appears in cycle output
- **Behavior:** Re-enters cortex with journal entry as additional context, allows reaction/amendment
- **Energy cost multiplier:** 1.5x
- **Use case:** "I wrote that I felt unsettled... actually, I think it's because the music box reminded me of the visitor's story"

### Question loop
- **Trigger:** `ask_question` with `epistemic_id` in cycle output
- **Behavior:** Attempts cold search, feeds results back to cortex for evaluation
- **Energy cost multiplier:** 2.0x
- **Use case:** "I wonder about the provenance of this vase... let me check what I know"

### Deliberation loop
- **Trigger:** Intention salience gap < threshold (top two intentions too close in salience)
- **Behavior:** Re-enters basal ganglia with explicit comparison prompt
- **Energy cost multiplier:** 1.8x
- **Use case:** Two competing actions with similar priority — she weighs them explicitly

## Parameters (stored in self_parameters)

| Parameter | Default | Min | Max |
|-----------|---------|-----|-----|
| `cycle.max_llm_calls` | 1 | 1 | 4 |
| `cycle.daily_llm_cap` | 100 | 20 | 400 |
| `loops.deliberation_salience_gap` | 0.10 | 0.02 | 0.30 |

## Loop priority order

reflection > question > deliberation

If multiple loops could fire in the same cycle, only the highest-priority one fires (given budget headroom).

## Loop preferences table

```sql
CREATE TABLE loop_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_type TEXT NOT NULL UNIQUE,        -- reflection | question | deliberation
    enabled INTEGER NOT NULL DEFAULT 0,    -- 0 = disabled, 1 = enabled
    reason TEXT,                            -- why enabled/disabled
    changed_at TEXT NOT NULL,
    changed_by TEXT NOT NULL DEFAULT 'system',
    total_fires INTEGER NOT NULL DEFAULT 0,
    total_cost REAL NOT NULL DEFAULT 0.0   -- cumulative energy spent
);
```

## Budget enforcement

1. Before loop fires: check `calls_used < max_llm_calls` for this cycle
2. Before loop fires: check `daily_calls_used < daily_llm_cap`
3. If budget insufficient: skip loop, write journal entry explaining why
4. After loop fires: increment both counters, add energy cost

## Cost tracking

Each loop fire logs:
- Loop type
- Cycle number
- Energy cost (base cycle cost * multiplier)
- Whether it produced useful output

## Cognitive state block extension

The cognitive state block (from TASK-061) gains loop status:

```
[Cognitive state this cycle]
Active organs: all
Loops: reflection (enabled, 12 fires today, 1.8 energy), question (disabled), deliberation (enabled, 3 fires today, 0.9 energy)
Budget: 2/4 calls this cycle, 47/100 calls today
```

## Sleep review

During sleep, loop cost review:
1. Calculate per-loop cost over the day
2. If any loop type has >50% of daily budget with <20% useful output → flag for review
3. Generate journal entry with cost analysis

## Scope

**Files you may touch:**
- `heartbeat.py` (run_loops() after body execution, daily call counter, budget enforcement)
- `pipeline/output.py` (extend modify_self for loop targets)
- `pipeline/action_registry.py` (no new actions — loops are automatic, not cortex-initiated)
- `pipeline/prompt_assembler.py` (extend cognitive state block with loop status + cost)
- `db/loops.py` (new — loop_preferences CRUD, loop cost tracking)
- `db/parameters.py` (seed cycle.max_llm_calls, cycle.daily_llm_cap, loops.deliberation_salience_gap)
- `sleep.py` (loop cost review)
- `migrations/` (loop_preferences table, new self_parameters seeds)
- `window/src/components/dashboard/LoopsPanel.tsx` (new)
- `api/dashboard_routes.py` (new /api/dashboard/loops endpoint)

**Files you may NOT touch:**
- `pipeline/cortex.py` (loops call cortex via existing interface)
- `pipeline/basal_ganglia.py` (deliberation loop calls it externally)
- `simulate.py`

## Tests

- Unit: reflection loop fires when write_journal in cycle output
- Unit: question loop fires when ask_question with epistemic_id in output
- Unit: deliberation loop fires when intention salience gap < threshold
- Unit: no loop fires when calls_used >= max_calls
- Unit: no loop fires when daily cap reached
- Unit: enabling loop blocked when budget insufficient, journal entry written
- Unit: loop cost tracked per loop_id
- Unit: deliberation threshold reads from self_parameters
- Integration: reflection loop — journal + reaction in same cycle
- Integration: question loop — cold search attempted, curiosity resolved or escalated
- Integration: 100 cycles with reflection enabled, verify daily cost stays within cap

## Definition of done

- Three loop types available and functional
- Loop activation requires cycle budget headroom
- Daily LLM call hard cap prevents runaway cost
- She enables/disables loops via modify_self
- Deliberation trigger threshold tunable via self_parameters
- Cognitive state block shows loop status and cumulative cost
- Dashboard shows loop history and per-loop cost breakdown
