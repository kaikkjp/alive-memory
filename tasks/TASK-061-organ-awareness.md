# TASK-061: Cognitive organ awareness (Frame 3)

## Problem

She has no introspective access to her own cognitive process. She doesn't know which pipeline stages (organs) are running, dormant, or suppressed — and has no mechanism to request changes. When an organ is disabled, she experiences unexplained gaps without understanding why.

## Solution

Add a `[Cognitive state this cycle]` prompt section showing which organs are active/dormant/suppressed and why. She can request organ changes via `modify_self(target="organ", ...)`. Invariant organs silently reject modification. Meta-sleep surfaces evidence when dormant organs cause gaps.

## Organ classification

**Invariant (cannot be modified):**
- Cortex — the LLM call itself
- Validator — output format/schema enforcement
- Affect — emotional state tracking
- Hippocampus — memory read/write

**Modifiable:**
- Cold Search — vector similarity search
- Sensorium — perception processing
- Thalamus — routing/prioritization
- Hypothalamus — drive regulation
- Basal Ganglia — action gating
- Any future organs added to the pipeline

## Organ preferences table

```sql
CREATE TABLE organ_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organ_name TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active',  -- active | dormant | suppressed
    reason TEXT,                             -- why it was changed
    changed_at TEXT NOT NULL,               -- UTC timestamp
    changed_by TEXT NOT NULL DEFAULT 'system', -- system | self | sleep
    review_count INTEGER NOT NULL DEFAULT 0  -- times reviewed by meta-sleep
);
```

## CognitiveStateReport dataclass

```python
@dataclass
class OrganState:
    name: str
    status: str  # active | dormant | suppressed
    reason: str | None

@dataclass
class CognitiveStateReport:
    organs: list[OrganState]
    cycle_number: int
    timestamp: str
```

## Prompt block format (hard cap: 200 tokens)

```
[Cognitive state this cycle]
Active: Cortex, Validator, Affect, Hippocampus, Sensorium, Thalamus, Hypothalamus, Basal Ganglia
Dormant: Cold Search (you disabled this — "rarely finding useful results")
```

If all organs active, simplified to:
```
[Cognitive state this cycle]
All organs active.
```

## modify_self for organs

```json
{
  "action": "modify_self",
  "target": "organ",
  "organ_name": "cold_search",
  "new_status": "dormant",
  "reason": "rarely finding useful results"
}
```

Invariant organ requests: no error, no event, just silently ignored. This prevents her from getting confused by error messages about organs she shouldn't be able to change.

## Meta-sleep review

During sleep, meta-sleep checks:
1. Are any organs dormant for >20 cycles?
2. Did any gaps appear that the dormant organ could have prevented?
3. If evidence of gaps found → generate journal entry suggesting re-evaluation

## Scope

**Files you may touch:**
- `models/pipeline.py` (add CognitiveStateReport, OrganState dataclasses)
- `heartbeat.py` (generate CognitiveStateReport at cycle start, read organ_preferences)
- `pipeline/prompt_assembler.py` (assemble_cognitive_state_block, enforce 200-token cap)
- `pipeline/output.py` (extend modify_self handler for organ targets)
- `db/organs.py` (new — organ_preferences CRUD)
- `sleep.py` (review_organ_preferences phase)
- `migrations/` (organ_preferences table)
- `window/src/components/dashboard/OrganPanel.tsx` (new)
- `api/dashboard_routes.py` (new /api/dashboard/organs endpoint)

**Files you may NOT touch:**
- `pipeline/cortex.py`
- `pipeline/basal_ganglia.py`
- `simulate.py`

## Tests

- Unit: invariant organs return no_effect silently, no error raised
- Unit: organ_preferences table correctly overrides default activation
- Unit: CognitiveStateReport reflects actual cycle state
- Unit: prompt block renders correctly and stays under 200 tokens
- Unit: meta-sleep generates journal entry when gaps detected after disabling organ
- Integration: disable cold_search -> 20 cycles -> cold_search absent from all cycles
- Integration: re-enable cold_search -> appears in next cycle

## Definition of done

- Cortex prompt includes cognitive state block every cycle (<=200 tokens)
- She can see which organs are active, dormant, or suppressed
- She can request organ changes via modify_self
- Invariant organs silently reject modification
- Meta-sleep surfaces evidence when dormant organs cause gaps
- Dashboard shows organ state history
