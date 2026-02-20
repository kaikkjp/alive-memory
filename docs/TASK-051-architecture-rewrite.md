# TASK-051: Rewrite architecture.md

**Depends on:** TASK-050 (shipped + 24h clean run verified)  
**Priority:** Medium — documentation debt, but blocks nothing  
**Scope:** Rewrite architecture.md to reflect the system as-built after TASK-050 changes

---

## Overview

After TASK-050 ships, architecture.md will be outdated. Multiple core systems changed: energy is gone, budget is real-dollar, day_memory uses event-driven floors, sleep consolidation order changed, basal ganglia lost a gate. This task rewrites the doc to match reality.

**Rule: Document what IS, not what we want.** Only describe systems that exist in code and have been verified by a 24h production run.

---

## Sections to Rewrite

### 1. Budget System (replaces "Energy System")

Old: Fictional 0-1 float energy with homeostatic pull, abstract action costs (0.05-1.5), separate budget tracker that summed all-time.

New:
- Energy = real dollars spent on LLM API calls
- Daily budget: configurable (default $2.00)
- `remaining = budget - SUM(cost_usd FROM llm_call_log WHERE created_at >= last_sleep_reset)`
- No stored energy state — one query, no drift
- At $0: skip cortex, sleep normal interval (180s), no spin loops
- External API costs (X posts, image gen, embeddings) deduct from same pool
- Display conversion: $2 budget = 200 energy (visitor-facing abstraction)

### 2. Basal Ganglia

Old: 5 gates including Gate 5 (energy gate) that checked energy level before allowing actions.

New:
- Gate 5 removed entirely
- Document remaining gates and their function
- No action is blocked by energy — only by budget exhaustion at the heartbeat level (no cortex call = no actions)

### 3. Day Memory / Moment Creation

Old: Salience formula combining resonance, drive deltas, monologue length, action diversity, mode bonuses. Threshold at 0.35 that most solo cycles couldn't reach.

New:
- Event-driven moment creation with guaranteed floors
- `write_journal` → salience 0.50 minimum
- `express_thought` with content → 0.40 minimum
- Thread created/updated → 0.55 minimum
- `read_content` executed → 0.60 minimum
- Visitor interaction → 0.70 minimum
- Internal conflict → 0.80 minimum
- Idle fidget only → no moment
- Modulation pushes salience UP from floors (drives, novelty, mood extremes), never below
- Expected output: 10-30 moments per active day

### 4. Sleep System

Old: Consolidation ran, then budget reset. Naps restored budget.

New:
- **Order: reset FIRST, then consolidate**
- Night sleep writes `last_sleep_reset` timestamp → budget resets to full
- Consolidation runs from fresh budget (costs ~$0.05-0.25 depending on moment count)
- She wakes with full budget minus consolidation cost
- Rich day (15 moments) → wakes at ~$1.88. Quiet day (3 moments) → wakes at ~$1.98
- **Naps no longer restore budget** — naps cost money (LLM calls), they don't generate it
- Nap consolidation still processes moments but is a budget expense

### 5. Action Registry

Old: Each action had an `energy_cost` field (0.05-1.5) that determined whether the character could afford to take the action.

New:
- No `energy_cost` field on actions
- Action cost is implicit: it's whatever the cortex LLM call costs in tokens
- Heavier actions (read_content, visitor engagement) naturally cost more because they put more tokens in the prompt
- No action is individually gated — budget gating happens at the heartbeat level

### 6. Hypothalamus

Old: Energy had homeostatic pull toward 0.5, modulated by hypothalamus alongside drives.

New:
- No energy homeostatic pull
- Document remaining drive modulation (social_hunger, diversive_curiosity, expression_need, etc.)
- Drives still have homeostatic dynamics — energy just isn't one of them anymore

### 7. Heartbeat Loop

Old: Checked energy budget (all-time sum), entered rest mode with 36s spin loops when exceeded.

New:
- Top of heartbeat: query `get_budget_remaining(db)`
- If remaining ≤ 0: log "[Heartbeat] Resting — budget spent", sleep 180s, no cortex call
- If remaining > 0: proceed with normal cycle (cortex call, action execution)
- No spin loops — rest uses same 180s interval as normal cycles
- Budget check is one SQL query, not a state machine

### 8. Dashboard

Old: Energy display showed fictional 0-1 float.

New:
- Budget display: "$X.XX / $Y.YY remaining" with progress bar
- Operator-adjustable budget input
- Cost breakdown: cortex calls vs external APIs (X posts, image gen) vs sleep consolidation
- Historical spend curve

---

## Sections to Verify (unchanged but confirm)

These systems should be unchanged by TASK-050 but verify they still match reality:

- **Cortex** — prompt composition, monologue generation
- **Drives** — social_hunger, diversive_curiosity, expression_need, mood coupling
- **Habits** — formation, decay, auto-fire thresholds
- **Threads / Trains of Thought** — creation, evolution, closing
- **Notification System** — content surfacing, save_for_later
- **Curiosity v2** — epistemic curiosity pipeline (should now work with read_content unblocked)
- **Visitor System** — conversation handling, trust, memory
- **Scene Composition** — if TASK-052 has shipped by then, include

---

## Process

1. Read current architecture.md top to bottom
2. Read TASK-050 implementation (actual code, not just spec)
3. Run 24h production data through diagnostic queries to confirm behavior matches expectations
4. Rewrite each section listed above
5. Verify unchanged sections still accurate
6. Remove any references to old energy system, fictional costs, energy gates

---

## Definition of Done

- Every system described in architecture.md matches the running production code
- No references to fictional energy points, energy_cost fields, or energy gates
- Budget system fully documented with real-dollar model
- Day memory event-driven floors documented
- Sleep consolidation order (reset → consolidate) documented
- Someone reading architecture.md can understand the full system without reading code
- No aspirational features described — only what's verified in production
