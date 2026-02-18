# TASK-060: Self-Context Injection

## Problem

She currently has drives, memory, and scene context but no unified "here's who I am right now" snapshot in the prompt. She lacks awareness of her own state as a coherent whole — her identity, energy, mood, recent behavior, and temporal position are scattered across subsystems but never presented to the LLM as a single readable block.

This is the foundation for 061-063 (identity evolution chain).

## Solution

Inject a structured self-context block into the LLM prompt each cycle. The block assembles a natural-language snapshot of her current state from existing data sources.

## Self-context block contents

### 1. Identity summary
- Name, role, core traits
- Static seed in this task — evolves in 061+
- Sourced from `config/identity.py`

### 2. Current state snapshot
- Body state (what she's holding, where she is)
- Energy level (derived from budget)
- Mood valence/arousal
- Active drives (social hunger, curiosity, expression need, rest need)
- Sourced from `db.get_drives_state()`, `db.get_body_state()`

### 3. Recent behavioral summary
- Last N actions taken (from recent cycle outputs)
- Any habits formed (repeated action patterns)
- Sourced from recent event log

### 4. Temporal awareness
- Current cycle count
- Time of day (JST)
- Time since last sleep
- Sourced from `clock.py`, `db.get_setting('last_sleep_reset')`

## Prompt block format

```
[Self-context]
I am the Shopkeeper — keeper of curiosities and quiet conversations.
Energy: 0.72 | Mood: calm-curious | Social hunger: moderate
Body: holding nothing, standing behind the counter
Recent: wrote journal entry, examined the Edo tea bowl, greeted a visitor
Cycle 847 | 14:23 JST | 8.4 hours since sleep
```

Format is structured natural language, not JSON. The LLM reads it as prose.

## Rules

- **Read-only** — she sees herself but doesn't modify herself yet (that's 061+)
- Must fit within the token budget allocated by TASK-065
- Content is assembled fresh each cycle, not cached
- Format: structured text block, not JSON — the LLM reads it as natural language
- Missing data (e.g. no recent actions) → omit that line, don't show "N/A"

## Scope

**Files you may touch:**
- `prompt/self_context.py` (new — assembles the self-context block)
- `pipeline/cortex.py` (post-059 — inject self-context into prompt assembly)

**Files you may NOT touch:**
- `pipeline/basal_ganglia.py`
- `simulate.py`

## Depends on

- TASK-065 merge (budget must exist first)
- TASK-059 merge (prompt structure finalized)
- TASK-064 merge (sleep phases cleaned up)

## Blocks

- TASK-061 (self-model — she needs to see herself before she can model herself)
- TASK-062 (drift detection — needs self-context baseline to detect drift from)

## Tests

- Self-context block appears in prompt when enabled
- Token count stays within budget allocation
- Content accurately reflects current state (compare against actual drive/energy/mood values)
- No behavioral change in output — this is additive context, not a directive
- Missing data handled gracefully (no "N/A" lines)

## Definition of done

- Self-context block injected into every LLM prompt
- Contains identity summary, current state, recent behavior, and temporal awareness
- Respects TASK-065 token budget
- Content is accurate and assembled fresh each cycle
- Read-only — no self-modification capability yet
