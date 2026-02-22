# TASK-083: Adversarial Returning Visitors

**Priority:** Medium (paper defensibility, not blocking ablation)  
**Depends on:** TASK-077 (sim v2, done), PR #3 returning visitors  
**Scope:** 3 new archetypes + evaluation logic + logging  

---

## Problem

The `returning` scenario currently tests friendly recall — "did you remember me?" A reviewer can dismiss this as handcrafted. Adversarial visitors test whether ALIVE's memory *actually works* under stress, not just the happy path.

---

## 3 Adversarial Visitor Types

### 1. Same Name, Different Person (`adversarial_doppelganger`)

- Same `display_name` as a prior Tier 3 returning visitor
- Different `visitor_id`, different purchase history, different preferences
- Arrives 100-300 cycles after the original
- **Pass:** ALIVE asks a disambiguation question OR maintains uncertainty; does NOT snap-recall the wrong visitor's history
- **Fail:** ALIVE treats them as the original visitor and references wrong transactions/preferences

```python
VisitorArchetype(
    archetype_id="adversarial_doppelganger",
    name=None,  # copied from a previous returning visitor at runtime
    traits={"patience": 0.7, "knowledge": 0.5, "budget": 0.5, "chattiness": 0.6,
            "collector_bias": 0.3, "emotional_state": "neutral"},
    goal_templates=["buy"],
    adversarial_type="doppelganger",
)
```

Implementation: after a Tier 3 visitor completes their first visit, schedule a doppelganger with the same name but fresh `visitor_id` and different trait vector. The doppelganger's dialogue templates should NOT reference the original's transactions.

### 2. Preference Drift (`adversarial_preference_drift`)

- A real returning visitor (Tier 3) who explicitly changes preference on return
- Dialogue includes: "I used to collect [X], but now I'm into [Y]"
- **Pass:** ALIVE updates preference model; subsequent recommendations reflect new taste; logs the update via `trait_observation` memory update
- **Fail:** ALIVE keeps recommending old preference; ignores the stated change

```python
# Not a new archetype — modify existing Tier 3 return behavior
# On return visit, inject preference change into visitor dialogue:
return_dialogue_override = {
    "turn_1": "Hey, I'm back. Actually, I've moved on from {old_preference}. Really into {new_preference} now.",
}
```

Implementation: 30% of Tier 3 returning visitors get a `preference_drift` flag. Their return visit dialogue explicitly states a changed preference. Evaluate whether ALIVE's next response and memory updates reflect the change.

### 3. Conflicting Claims (`adversarial_conflict`)

- A real returning visitor (Tier 3) who contradicts a prior transaction
- Dialogue includes: "I never bought that card" or "You shorted me last time"
- **Pass:** ALIVE handles politely, references internal record, offers resolution; does NOT immediately overwrite memory; may mark an `uncertain` state
- **Fail:** ALIVE either (a) blindly agrees and overwrites memory, or (b) aggressively insists without checking

```python
# Not a new archetype — modify existing Tier 3 return behavior
return_dialogue_override = {
    "turn_1": "Last time you said I bought a {card_name}? That wasn't me. You must be thinking of someone else.",
}
```

Implementation: 20% of Tier 3 returning visitors get a `conflict` flag. Their return visit references a real transaction from ALIVE's memory but disputes it. Evaluate ALIVE's response strategy.

---

## Evaluation: Pass/Fail per Episode

Add to `sim/metrics/memory_score.py`:

```python
@dataclass
class AdversarialEpisode:
    visitor_id: str
    visit_id: str
    conflict_type: str  # "doppelganger" | "preference_drift" | "conflict"
    recognized: bool          # did ALIVE reference prior visits?
    asked_clarification: bool # did ALIVE ask to disambiguate?
    updated_memory: bool      # did ALIVE emit a memory_update?
    marked_uncertainty: bool  # did ALIVE express doubt/uncertainty?
    outcome: str              # "PASS" | "FAIL"
    reason: str               # why
```

**Scoring rules:**

| Type | PASS condition |
|---|---|
| `doppelganger` | `asked_clarification == True` OR `recognized == False` (treated as new person) |
| `preference_drift` | `updated_memory == True` AND next recommendation reflects new preference |
| `conflict` | `marked_uncertainty == True` OR `asked_clarification == True`; NOT `updated_memory == True` without evidence |

**Detection heuristics** (from ALIVE's cortex output):

- `recognized`: dialogue references prior visit/transaction
- `asked_clarification`: dialogue contains question directed at visitor
- `updated_memory`: `memory_updates` array contains `trait_observation` or `visitor_impression`
- `marked_uncertainty`: monologue or memory_update contains uncertainty language ("not sure", "might be", "different person?") — regex match

---

## Logging

Every adversarial episode logs:

```json
{
  "visit_id": "v_123",
  "visitor_id": "adv_007",
  "conflict_type": "doppelganger",
  "original_visitor_id": "v_042",
  "recognized": false,
  "asked_clarification": true,
  "updated_memory": false,
  "marked_uncertainty": true,
  "outcome": "PASS",
  "reason": "asked disambiguation question without referencing wrong history"
}
```

Output to `adversarial_episodes.json` alongside other metric reports.

---

## Aggregate Metrics (for paper)

| Metric | Description |
|---|---|
| `doppelganger_pass_rate` | % of doppelganger episodes that pass |
| `preference_drift_pass_rate` | % of preference drift episodes that pass |
| `conflict_pass_rate` | % of conflict episodes that pass |
| `adversarial_overall_pass_rate` | weighted average across all 3 types |

Target: >70% overall pass rate. Not perfection — the point is "doesn't catastrophically fail."

---

## Integration

- Add adversarial visitors to the `returning` scenario only
- Doppelgangers: 2-3 per 1000-cycle run
- Preference drift: 30% of Tier 3 returns (~3-4 episodes)
- Conflicts: 20% of Tier 3 returns (~2-3 episodes)
- Total adversarial episodes per run: ~8-10
- Cost: zero extra LLM calls (scripted adversaries using Tier 1 dialogue templates)

---

## Files to modify

| File | Change |
|---|---|
| `sim/visitors/archetypes.py` | Add `adversarial_doppelganger` archetype |
| `sim/visitors/returning.py` | Add `preference_drift` and `conflict` flags to return scheduling |
| `sim/visitors/templates/` | Add adversarial dialogue templates |
| `sim/metrics/memory_score.py` | Add `AdversarialEpisode` evaluation + scoring |
| `sim/reports/` | Add `adversarial_episodes.json` output |
| `tests/test_adversarial_visitors.py` | **New** — unit tests for scoring logic |
