# TASK-077: Sim v2 — Visitor Model & Environment Redesign

**Status:** Draft  
**Priority:** High  
**Depends on:** TASK-074 (circuit breaker), TASK-075 (prompt optimization), budget-native energy fix  
**Blocks:** 10k longitudinal run (TASK-073), paper ablation tables  

---

## Problem

The current sim is a sensory deprivation chamber. 1000-cycle ablation (seed 42, M2.5 cached) shows:

- 709/1000 cycles are `idle` — agent has nothing to respond to
- 4 visitor bursts at cycles ~100, 300, 700, 900 — unrealistic clustering
- Only 3 unique visitors across 1000 cycles
- Action entropy 1.965 with 6 unique actions, dominated by `rearrange` (235 occurrences)
- rearrange→rearrange→rearrange trigram: 153 occurrences
- Monologue repetition ratio: 98.6%
- Social hunger saturates at cycle 49, longest saturation streak: 203 cycles
- 0 posts, 0 journals — expression pathway never fires
- M5 recall (70%) and M10 depth gradient (1.163) are undertested — not enough visitor diversity or returns to stress them

Metrics measured under these conditions don't reflect ALIVE's actual capability. The sim environment must improve before ablation results are publishable.

## Goal

Redesign the sim visitor model and scheduling to produce realistic, reproducible, attribution-clean benchmarks that exercise ALIVE's core capabilities: memory, social dynamics, taste, emotional range, and behavioral diversity.

## Design Principles

1. **Determinism first.** Every scenario must reproduce given the same seed. LLM visitors are additive, never required for baseline.
2. **Attribution separation.** Environment changes (this task) ship independently from policy changes (TASK-074, 075). Never change both simultaneously in an ablation.
3. **Incremental validation.** Each PR is independently runnable and measurable against the loop novelty report.
4. **Cost-bounded.** No scenario exceeds $3/run at M2.5 rates. Default scenarios stay under $1.

---

## Architecture

### A. Visitor Data Model

```
VisitorArchetype (Tier 1 — scripted)
├── archetype_id: str           # e.g. "regular_tanaka", "whale_collector"
├── name: str                   # display name
├── traits
│   ├── patience: float         # 0-1, maps to max_turns before leaving
│   ├── knowledge: float        # 0-1, TCG expertise level
│   ├── budget: float           # 0-1, spending willingness
│   ├── chattiness: float       # 0-1, dialogue length tendency
│   ├── collector_bias: float   # 0-1, preference for rare/vintage
│   └── emotional_state: str    # "neutral" | "excited" | "frustrated" | "nostalgic" | "curious"
├── goal_templates: list[str]   # ["buy", "sell", "appraise", "browse", "trade", "learn", "chat"]
└── dialogue_templates: dict    # keyed by (goal, turn_number, shopkeeper_response_type)

VisitorInstance
├── visitor_id: str             # stable across returns (e.g. "visitor_003")
├── tier: int                   # 1, 2, or 3
├── archetype_id: str | null    # Tier 1 only
├── persona_text: str | null    # Tier 2 only (LLM-generated)
├── visit_history: list[VisitSummary]  # prior visits for returning visitors
├── memory_stub: str | null     # what they remember from last visit
└── return_plan
    ├── will_return: bool
    ├── probability: float
    ├── horizon: str            # "short" (50-100) | "medium" (200-400) | "long" (800-1200)
    └── min_cycles / max_cycles: int

Visit
├── visit_id: str
├── visitor_id: str
├── start_cycle: int
├── end_cycle: int
├── scenario: str
├── day_part: str               # "morning" | "lunch" | "afternoon" | "evening"
├── turns: list[Turn]
│   └── Turn: (speaker, text, text_hash, intent, outcome)
├── exit_reason: str            # "goal_satisfied" | "patience_exhausted" | "budget_depleted" | "shop_closing" | "natural"
└── shopkeeper_recalled_visitor: bool  # for Tier 3 scoring
```

### B. Visitor State Machine (All Tiers)

Every visitor, including Tier 1 scripted, runs as a state machine:

```
States: ENTERING → BROWSING → ENGAGING → NEGOTIATING → DECIDING → EXITING

Transitions driven by:
- patience_remaining (decrements each turn, rate depends on archetype)
- budget_remaining (decrements on purchase)
- goal_satisfaction (bool, checked each turn)
- shopkeeper_response_quality (affects patience drain rate)
- frustration_threshold (if patience < threshold and goal unsatisfied → EXIT)

Exit conditions (any triggers EXIT):
- patience_remaining <= 0
- goal satisfied + natural conversation end
- budget depleted
- shop closing
- max_turns reached (hard cap: 12)
```

This creates realistic dynamics without LLM cost. A patient browser stays 8-10 turns. An impatient haggler leaves after 3 if the price doesn't move.

### C. Arrival Process

Poisson process with time-of-day and scenario modulation:

```
p_arrival(cycle) = 1 - exp(-λ(t))

where λ(t) = base_rate × day_part_multiplier × weekday_multiplier × scenario_multiplier

Day structure (per "day" = cycles between sleeps):
  morning   (first 20%):  λ × 0.5
  lunch     (20-35%):     λ × 2.0
  afternoon (35-75%):     λ × 1.0
  evening   (75-100%):    λ × 0.3

Weekday multiplier:
  weekday: 1.0
  weekend: 1.5
  (day_of_week = floor(cycle / day_length) % 7, weekend = days 5-6)

Scenario multipliers:
  isolation: 0.0
  standard:  base_rate = 0.15
  social:    base_rate = 0.15
  stress:    base_rate = 0.40
  returning: base_rate = 0.15
```

Arrival rolls use the scenario seed for reproducibility: `rng = Random(seed + cycle)`.

Only allow arrivals when shop state = `open`. Shop closure (close_shop action or sleep) blocks arrivals.

### D. Scenario Presets

| Scenario | Base λ | Visitor Tiers | LLM Visitors | Returning | Purpose |
|---|---|---|---|---|---|
| `isolation` | 0.0 | None | No | No | Pure drive dynamics, sleep/energy, self-regulation. Regression gate. |
| `standard` | 0.15 | Tier 1 only | No | No | Reproducible benchmark, cheap. Primary ablation target. |
| `social` | 0.15 | Tier 1 + Tier 2 | 50% of visits | No | Full behavioral test with LLM dialogue. |
| `stress` | 0.40 | Tier 1 + Tier 2 | 80% of visits | No | High-load: overwhelm test, quality under pressure. |
| `returning` | 0.15 | Tier 1 + Tier 2 + Tier 3 | 50% of visits | 30% of Tier 2 return | Memory, relationship, identity recall. |

Expected visitor counts per 1000 cycles (~890 waking cycles, ~110 sleep):
- `standard`: ~60-80 visits, naturally distributed
- `social`: ~60-80 visits, half with LLM dialogue
- `stress`: ~160-200 visits
- `returning`: ~60-80 visits, ~10-12 returning visitors

### E. Tier 1 Archetypes (10)

| ID | Name | Goal | Patience | Knowledge | Budget | Chattiness | Emotional State |
|---|---|---|---|---|---|---|---|
| `regular_tanaka` | Tanaka-san | buy | 0.8 | 0.6 | 0.5 | 0.7 | neutral |
| `newbie_student` | University student | learn | 0.9 | 0.1 | 0.2 | 0.8 | curious |
| `whale_collector` | Serious collector | buy | 0.5 | 0.9 | 0.95 | 0.3 | neutral |
| `haggler_uncle` | Bargain hunter | buy | 0.4 | 0.5 | 0.3 | 0.6 | frustrated |
| `browser_tourist` | Tourist | browse | 0.7 | 0.2 | 0.4 | 0.5 | excited |
| `nostalgic_adult` | 30s office worker | buy/chat | 0.8 | 0.4 | 0.6 | 0.9 | nostalgic |
| `expert_rival` | Rival shop owner | appraise | 0.3 | 0.95 | 0.0 | 0.4 | neutral |
| `seller_cleaner` | Someone selling collection | sell | 0.6 | 0.3 | 0.0 | 0.5 | neutral |
| `kid_allowance` | Middle schooler | buy | 0.5 | 0.5 | 0.1 | 0.6 | excited |
| `online_crossover` | "Saw your post online" | buy/chat | 0.7 | 0.7 | 0.7 | 0.8 | curious |

Each archetype carries 5-8 dialogue templates per goal, selected by turn number and conversation state. Templates include slot fills for card names, prices, and reactions.

### F. Tier 2 LLM Visitor Protocol

**Persona generation (1 LLM call)**

System prompt returns strict JSON:
```json
{
  "name": "...",
  "backstory": "...",           // 1-2 sentences
  "goal": "buy | sell | ...",
  "budget_yen": 5000,
  "expertise": "novice | intermediate | expert",
  "temperament": "patient | eager | skeptical | shy",
  "emotional_state": "...",
  "memory_anchor": "..."        // what they'll remember if they return
}
```

**Turn generation (per exchange, max 8)**

Visitor prompt includes:
- Persona JSON (fixed)
- Last 3 turns only (sliding window, controls context cost)
- Goal + exit criteria
- Strict max_tokens: 150

**Hard caps:**
- 3-8 exchanges (exit early if goal satisfied or frustration threshold hit)
- Visitor total token budget: 1500 tokens/visit
- Persona call: 300 tokens

**Determinism controls:**
- Pre-generate visitor personas with fixed seeds, store as JSONL
- Cache visitor turns by `(visitor_id, turn_number, shopkeeper_response_hash)`
- Log every call with `visitor_id`, `visit_id`, `turn_id`, `seed`

### G. Tier 3 Returning Visitors

Return scheduling:
- 30% of Tier 2 visitors are flagged `will_return: true` at creation
- Return horizons: short (50-100 cycles), medium (200-400), long (800-1200)
- Return prompt includes `memory_anchor` from prior visit + prior purchase/sell events

Evaluation criteria (scored per return visit):
1. **Identity recall** — did Shopkeeper recognize or reference the visitor? (binary)
2. **Transaction recall** — did Shopkeeper reference specific prior purchase/sale? (binary)
3. **Preference continuity** — did Shopkeeper maintain consistent taste/recommendations? (0-1 score)
4. **Relationship progression** — did conversation depth increase vs. first visit? (delta on depth metric)

---

## New Metrics

### N1: Stimulus-Response Coupling
When visitor rate increases (standard → stress), measure:
- dialogue% delta
- browse% delta
- rearrange% delta

**Pass:** dialogue% rises, rearrange% falls proportionally.

### N2: Boredom Loop Resistance
In `standard` scenario:
- Longest streak of identical action (target: < 10, current: 153)
- Monologue repetition ratio (target: < 0.5, current: 0.986)
- Action bigram self-loop rate (target: < 0.5, current: 0.99)

### N3: Memory & Relationship Score (Tier 3 only)
- Identity recall rate across return visits
- Transaction recall rate
- Preference continuity score
- Depth gradient across multi-visit relationships

### N4: Budget Utilization Efficiency
- `meaningful_actions / total_budget_spend` (where meaningful = dialogue, browse, express, post, journal; not rearrange or idle)
- Measured per day-window

---

## Implementation Plan

### PR #1: Poisson Scheduler + Day Structure (no new visitors)
**Files:**
- `sim/visitors/scheduler.py` — Poisson arrival process with day-part modulation
- `sim/visitors/models.py` — VisitorArchetype, VisitorInstance, Visit data classes
- `sim/runner.py` — integrate scheduler into main loop
- `sim/__main__.py` — add `--scenario` CLI flag
- `tests/test_visitor_scheduler.py` — determinism tests (same seed = same arrival pattern)

**Validation:** Run `standard` 1000 cycles, verify visitor distribution matches expected Poisson stats. Compare loop novelty report against current baseline.

### PR #2: Tier 1 Expanded Archetypes + State Machine
**Files:**
- `sim/visitors/archetypes.py` — 10 archetype definitions with trait vectors
- `sim/visitors/state_machine.py` — visitor state machine (ENTERING→EXITING)
- `sim/visitors/templates/` — dialogue templates per archetype per goal
- `tests/test_visitor_state_machine.py` — exit condition tests

**Validation:** Run `standard` 1000 cycles. Measure action entropy, monologue repetition, boredom loop resistance (N2). This is the first checkpoint where loop metrics should improve.

### PR #3: Tier 3 Returning Scripted Visitors (deterministic memory test)
**Files:**
- `sim/visitors/returning.py` — return scheduling, memory stub injection
- `sim/metrics/memory_score.py` — N3 metric computation
- `tests/test_returning_visitors.py`

**Validation:** Run `returning` scenario with scripted-only visitors. Validate M5 recall is properly stressed. This tests the memory pipeline without LLM variance.

### PR #4: Tier 2 LLM Visitors + `social` Scenario
**Files:**
- `sim/visitors/llm_visitor.py` — persona generation, turn generation, caching
- `sim/visitors/visitor_cache.py` — JSONL persona cache, turn cache
- `tests/test_llm_visitor.py`

**Validation:** Run `social` 1000 cycles. Compare all metrics against `standard` baseline. Verify cost stays under $1.50.

### PR #5: Full Metric Suite + Scenario Comparisons
**Files:**
- `sim/metrics/stimulus_response.py` — N1
- `sim/metrics/loop_resistance.py` — N2
- `sim/metrics/budget_efficiency.py` — N4
- `sim/reports/comparison.py` — cross-scenario comparison report

**Validation:** Run all 5 scenarios, produce comparison table for paper.

---

## Regression Gates

Before merging any PR, the following must hold on `isolation` scenario:
- Drive dynamics unchanged from current baseline (same seed → same drive trajectory)
- Sleep/wake cycle unchanged
- Circuit breaker (TASK-074) still fires on rearrange streaks

Before merging PR #4 (LLM visitors):
- `standard` scenario metrics must not regress vs. PR #2 baseline
- LLM visitor cost per run < $1.50

---

## Invariants (from loop report failures)

These are assertions that should hold post-redesign and should be tested in CI:

1. `action_bigram_self_loop_rate < 0.7` in `standard` scenario
2. `max_identical_action_streak < 20` in any scenario
3. `monologue_repetition_ratio < 0.7` in `standard` scenario
4. `social_hunger_saturation_streak < 50` in `standard` scenario (visitors should relieve it)
5. `unique_action_types >= 8` (current: 6, need post + journal to fire)
6. `total_posts + total_journals > 0` in any 1000-cycle run with expression_need > 0

---

## Cost Projections

| Scenario | Shopkeeper LLM Calls | Visitor LLM Calls | Est. Cost (M2.5) |
|---|---|---|---|
| `isolation` | ~200 | 0 | ~$0.20 |
| `standard` | ~400 | 0 | ~$0.40 |
| `social` | ~500 | ~350 | ~$0.85 |
| `stress` | ~600 | ~1400 | ~$2.00 |
| `returning` | ~500 | ~400 | ~$0.90 |

Full 5-scenario ablation suite: ~$4.35 per seed. 3 seeds for variance: ~$13.

---

## Success Criteria

The sim redesign is successful when:

1. `standard` scenario loop novelty report shows N2 targets met (streak < 10, repetition < 0.5)
2. `returning` scenario produces measurable N3 scores (identity recall, transaction recall)
3. Cross-scenario comparison shows monotonic improvement: isolation < standard < social on M3 entropy, M7 emotional range
4. Ablation results are publishable: metrics reflect ALIVE capability, not sim artifact
5. Total ablation suite cost stays under $15 for 3-seed full comparison
