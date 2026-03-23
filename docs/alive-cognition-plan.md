# alive-cognition / alive-memory Plan

## Objective

Split the repo into two packages in the same monorepo:

- **alive_memory**: storage, consolidation, recall, hot memory, embeddings, formation
- **alive_cognition**: thalamus (multi-axis salience), affect, drives, identity, meta

---

## 1. Package boundary

### 1.1 Responsibility split

**alive_memory** — What is stored, consolidated, and recalled?

Owns: storage, hot/cold memory, consolidation, recall, embeddings, DayMoment formation, multimodal input, filesystem watchers, LLM provider abstraction, server/API, adapters.

**alive_cognition** — What matters right now, and who am I?

Owns: thalamus/salience, affect, drives, identity, meta-controller.

### 1.2 Move map

**Move into alive_cognition:**
- `alive_memory/intake/thalamus.py`
- `alive_memory/intake/affect.py`
- `alive_memory/intake/drives.py`
- `alive_memory/identity/*`
- `alive_memory/meta/*`

**Stay in alive_memory:**
- `alive_memory/intake/formation.py`
- `alive_memory/intake/multimodal.py`
- `alive_memory/intake/file_watcher.py`
- everything else (consolidation, recall, hot, storage, embeddings, server, adapters)

### 1.3 Dependency direction

```
alive_cognition -> alive_memory.types, alive_memory.config, alive_memory.storage.base
alive_memory  -/-> alive_cognition
```

Cognition depends on memory primitives. Memory never imports cognition.

---

## 2. Directory structure

```
alive_memory/
  intake/
    __init__.py
    formation.py
    multimodal.py
    file_watcher.py
  consolidation/
  recall/
  hot/
  storage/
  embeddings/
  llm/
  server/
  adapters/
  types.py
  config.py
  clock.py

alive_cognition/
  __init__.py             # re-exports
  thalamus.py             # Thalamus class + composite scoring
  channels.py             # 4 channel scorers (deterministic)
  habituation.py          # novelty decay + repetition buffer
  overrides.py            # hard rules (safety, direct request, spam)
  types.py                # EventSchema, ChannelScores, SalienceBand, ScoredPerception
  affect.py               # moved from intake/affect.py
  drives.py               # moved from intake/drives.py
  identity/               # moved unchanged
  meta/                   # moved unchanged
```

---

## 3. Types

### 3.1 Shared (stay in alive_memory.types)

`EventType`, `Perception`, `DriveState`, `MoodState`, `SelfModel`, `DayMoment`, storage primitives.

Memory is the lower-level layer. Cognition imports these.

### 3.2 Cognition-only (alive_cognition/types.py)

```python
@dataclass
class EventSchema:
    event_type: EventType
    content: str
    source: str                        # "chat", "sensor", "tool", "system"
    actor: str                         # "user", "agent", "environment"
    timestamp: datetime
    metadata: dict[str, Any]           # host context goes here


class ChannelScores:
    relevance: float                   # 0-1: goal + actionability
    surprise: float                    # 0-1: novelty + memory value
    impact: float                      # 0-1: affect + safety
    urgency: float                     # 0-1: time sensitivity


class SalienceBand(Enum):
    DROP = 0                           # 0.00-0.30
    STORE = 1                          # 0.31-0.70
    PRIORITIZE = 2                     # 0.71-1.00


class ScoredPerception:
    event: EventSchema
    channels: ChannelScores
    salience: float                    # composite
    band: SalienceBand
    reasons: list[str]                 # human-readable
    novelty_factor: float              # habituation decay
    timestamp: datetime
```

---

## 4. Thalamus

### 4.1 Purpose

Decides how much attention an event deserves. Attention control layer before memory formation. Not the reasoning system.

Properties: cheap, deterministic, low-latency, auditable.

### 4.2 API

```python
class Thalamus:
    def __init__(
        self,
        config: AliveConfig | None = None,
        weights: ChannelWeights | None = None,
        identity_keywords: list[str] | None = None,
    ): ...

    def perceive(self, event: EventSchema) -> ScoredPerception:
        """Score an event. Deterministic, no LLM."""

    def update_context(
        self,
        *,
        active_goals: list[str] | None = None,
        current_drives: DriveState | None = None,
        current_mood: MoodState | None = None,
        identity_keywords: list[str] | None = None,
    ) -> None:
        """Update context for context-dependent scoring."""

    def reset_habituation(self) -> None:
        """Clear habituation buffer (e.g., after sleep)."""
```

---

## 5. Channels

Each channel is a pure scorer: `(event, context) -> (score, reasons)`

### 5.1 Relevance

Question: does this matter to active goals, identity, drives, or is it actionable?

Absorbs: goal_relevance + actionability from the original 6-channel design.

Signals:
- active goal keyword overlap (from `metadata["active_goals"]` if host provides)
- identity keyword match
- drive alignment
- contains explicit question/command/request
- mentions known tools/actions

### 5.2 Surprise

Question: how novel is this, and would storing it improve future decisions?

Absorbs: surprise + memory_value from the original 6-channel design.

Signals:
- novelty vs habituation buffer
- event-type rarity in recent window
- information density (content word ratio, word length, named entities)
- preference revelation / new world-model facts
- embedding distance from recent context (if host provides embedding)

### 5.3 Impact

Question: how emotionally, socially, economically, or safety-relevant is this?

Signals:
- affective keywords (praise, insult, frustration, gratitude)
- reward / punishment / risk markers
- safety patterns
- trust or conflict signals

### 5.4 Urgency

Question: does delayed response reduce value?

Signals:
- explicit time expressions ("now", "urgent", "deadline", "today")
- failure severity
- request immediacy
- expiring states

---

## 6. Composite scoring

### 6.1 Weights

```python
DEFAULT_WEIGHTS = ChannelWeights(
    relevance=0.35,
    surprise=0.25,
    impact=0.20,
    urgency=0.20,
)
```

### 6.2 Formula

```python
base = (
    weights.relevance * channels.relevance
    + weights.surprise * channels.surprise
    + weights.impact   * channels.impact
    + weights.urgency  * channels.urgency
)

final = clamp(base * novelty_factor + hard_override, 0.0, 1.0)
```

Where:
- `novelty_factor`: from habituation, 0.4-1.0
- `hard_override`: force-high or force-low from overrides

---

## 7. Salience bands

| Band | Range | Action |
|---|---|---|
| DROP | 0.00-0.30 | return None, no DayMoment |
| STORE | 0.31-0.70 | normal DayMoment, reaches hot/cold via consolidation |
| PRIORITIZE | 0.71-1.00 | DayMoment + flag, immediate hot write, optional cold embed |

### 7.1 Band-to-tier mapping

| Band | Tier 1 (day/SQLite) | Tier 2 (hot/markdown) | Tier 3 (cold/embeddings) |
|---|---|---|---|
| DROP | skip | — | — |
| STORE | DayMoment | via consolidation | via consolidation |
| PRIORITIZE | DayMoment + flag | immediate hot write | immediate cold embed |

---

## 8. Hard overrides

**Force high (PRIORITIZE):**
- direct user request / explicit command or question
- safety risk pattern
- host-provided `metadata["salience"]` override

**Force low (DROP):**
- exact duplicate in dedup window
- system heartbeat / routine log
- known spam pattern

Deterministic and explicit. No ML.

---

## 9. Habituation

In-memory ring buffer (`collections.deque`, configurable max size).

```python
class HabituationBuffer:
    def novelty_factor(self, event: EventSchema) -> float:
        """0.4-1.0. Decays if similar events seen recently.
        Similarity: same source + same type + content fingerprint overlap.
        """

    def record(self, event: EventSchema) -> None:
        """Add event to buffer after scoring."""
```

Habituation reduces attention. It does not declare resolution.

---

## 10. Integration

### 10.1 Intake flow

```
AliveMemory.intake(event_type, content, metadata)
  -> normalize to EventSchema
  -> thalamus.perceive(event) -> ScoredPerception
  -> affect.apply_affect(...)
  -> drives.update_drives(...) / update_mood(...)
  -> route by band:
       DROP       -> return None
       STORE      -> formation.form_moment() -> DayMoment
       PRIORITIZE -> formation.form_moment() + immediate hot/cold write
  -> return DayMoment | None
```

### 10.2 Backward compatibility

`AliveMemory.intake(event_type, content, metadata)` signature unchanged. Internally constructs EventSchema.

New: `AliveMemory.intake_event(event: EventSchema)` for hosts building structured events.

Bridge: `ScoredPerception.to_perception()` for legacy code.

---

## 11. Deprecation shims

One release cycle. Old paths re-export with `DeprecationWarning`:

```python
# alive_memory/intake/thalamus.py (shim)
import warnings
warnings.warn("use alive_cognition.thalamus", DeprecationWarning, stacklevel=2)
from alive_cognition.thalamus import Thalamus  # noqa: F401
```

Same for affect, drives, identity/*, meta/*.

---

## 12. Packaging

Single `pyproject.toml`. Both packages in one wheel. Split repos only if release cycles diverge.

---

## 13. Execution sequence

| Step | What | Risk |
|---|---|---|
| **1** | Create `alive_cognition/` skeleton | None |
| **2** | Move affect, drives, identity, meta | Low — pure moves |
| **3** | Deprecation shims at old paths | None |
| **4** | Implement types.py | None |
| **5** | Implement channels.py (4 scorers) | None |
| **6** | Implement thalamus.py (composite + banding) | None |
| **7** | Implement habituation.py | None |
| **8** | Implement overrides.py | None |
| **9** | Rewire `AliveMemory.intake()` + add `intake_event()` | Medium |
| **10** | Rewire `sleep.py` imports | Low |
| **11** | Update tests | Medium |
| **12** | Update pyproject.toml, CLAUDE.md | Low |

Steps 1-8 are additive. Step 9 is the integration point.

---

## 14. Testing plan

**Unit:** each channel scorer, composite weighting, band assignment at boundaries, hard overrides, habituation decay, `ScoredPerception.to_perception()` bridge.

**Integration:** `AliveMemory.intake()` end-to-end, `intake_event()` path, DayMoment formation varies by band, PRIORITIZE forces hot/cold write.

**Regression:** old import paths work with warning, legacy Perception bridge, memory code unaffected.

---

## 15. Deferred — with rationale for future addition

### 15.1 Tension tracker (was section 11)

**What:** per-topic counters that accumulate pressure on unresolved recurring issues. Separate from habituation — habituation says "I've seen this," tension says "this is still unresolved."

**Why deferred:** no evidence yet that habituation alone loses chronic failures. Build habituation first, observe whether repeated unresolved events actually get suppressed below useful thresholds. If they do, tension is the fix.

**Trigger to add:** benchmarks show the system habituates to recurring errors and stops promoting them, even though no resolution occurred.

**Design when needed:** `TensionTracker` class, per-topic `(source, type, fingerprint)` counters, `tension_boost` additive term in composite formula, `resolve_tension(topic)` method on Thalamus. Add `tension_boost` field to `ScoredPerception`.

### 15.2 LLM semantic assist (was sections 12, 4.2 Tier 1)

**What:** selective LLM calls for ambiguous/language-heavy events. Two-tier model: Tier 0 deterministic (every event), Tier 1 LLM (selective). `perceive_deep()` async method, `should_escalate()` policy, `SemanticFeatures` structured output, merge strategy with uncertainty-capped blending.

**Why deferred:** the current system has no LLM in the thalamus and works. The deterministic upgrade (4 channels + habituation + overrides) is a large improvement on its own. Adding LLM introduces latency, cost, prompt fragility, and inconsistent thresholds. Build deterministic first, benchmark, find where it actually fails.

**Trigger to add:** benchmarks show the deterministic scorer consistently misjudges events where meaning depends on tone, intent, or implicit context (e.g., "fine, whatever" scored low when user is frustrated). These cases should cluster around human language events in the gray band.

**Design when needed:**
- `semantic.py` — LLM feature extraction, `SemanticFeatures` dataclass
- `escalation.py` — `should_escalate(event, tier0_result) -> bool`
- `perceive_deep()` on Thalamus — async, calls Tier 0 then optionally Tier 1
- Merge: `blend = min(0.5, 1.0 - semantic.uncertainty)`, lerp channel scores
- LLM sizing: Haiku-class max in thalamus, heavier models only in consolidation
- Never output single salience number from LLM, always structured sub-scores + rationale
- Deterministic controller retains final authority

### 15.3 AliveCognition wrapper class (was section 16)

**What:** package-level orchestrator that owns Thalamus, provides `perceive()` / `perceive_deep()` / `update_context()`.

**Why deferred:** it's a class with one field that delegates. `AliveMemory` owns the `Thalamus` directly. No standalone cognition use case exists yet.

**Trigger to add:** a second consumer of cognition appears (e.g., `alive-reasoning` or `alive-planning` that needs salience scoring without memory).

### 15.4 Expanded channels (6 → 4 was a deliberate cut)

**What:** original design had 6 channels: goal_relevance, surprise, value_impact, urgency, actionability, memory_value.

**Why cut to 4:** actionability overlaps heavily with goal_relevance (relevant goals are usually actionable). memory_value overlaps with surprise (novel things are worth storing). 4 channels carry the same practical signal with less surface area.

**Trigger to expand:** tuning reveals that goal-relevant-but-unactionable events (e.g., "the deploy is blocked" when agent can't unblock it) need different treatment from actionable ones. Or that novel-but-not-worth-storing events (e.g., random trivia) pollute memory.

### 15.5 Expanded bands (5 → 3 was a deliberate cut)

**What:** original design had 5 bands: DISCARD, PERIPHERAL, WORKING, FOCUS, COMMIT.

**Why cut to 3:** PERIPHERAL vs WORKING has no behavioral difference in the current system — both write a DayMoment, both reach hot/cold via consolidation. FOCUS vs COMMIT is also marginal — both mean "pay attention now." 3 bands map cleanly to 3 real actions: drop, store normally, prioritize.

**Trigger to expand:** routing logic actually diverges. E.g., if we need a "buffer briefly but don't store" behavior (PERIPHERAL) separate from "store for consolidation" (WORKING). Or if "reprioritize agent" (FOCUS) needs different handling from "force cold embed" (COMMIT).

### 15.6 bridge.py (intake handoff file)

**What:** explicit file in `alive_memory/intake/` for the handoff between cognition output and formation.

**Why dropped:** `formation.py` already is the bridge. Adding another file wraps one function call.

**Trigger to add:** the handoff logic grows beyond EventSchema → formation.form_moment() — e.g., band-specific routing needs multiple code paths with shared preprocessing.

### 15.7 source_trust and context_gain modifiers

**What:** multiplicative modifiers in composite formula: `source_trust` (0.6-1.2 from metadata/config) and `context_gain` (0.7-1.3 from current agent state like task depth, interruption cost).

**Why deferred:** no current source trust model exists, and context gain requires agent-state awareness the SDK doesn't have. The formula works with just `novelty_factor` and `hard_override` for now.

**Trigger to add:** hosts start passing trust scores per source, or the agent framework exposes current task depth / interruption cost.

---

## 16. Canonical decisions

- Two packages in one monorepo: **yes**
- Single pyproject.toml: **yes**
- Cognition depends on memory primitives: **yes**
- Four-channel salience: **yes** (collapsed from 6)
- Three salience bands: **yes** (collapsed from 5)
- Deterministic only, no LLM in thalamus: **yes** (LLM deferred)
- Habituation as stateful subsystem: **yes**
- No tension tracker: **deferred** (add when habituation proves insufficient)
- No AliveCognition wrapper: **deferred** (add when second consumer exists)
- Backward-compatible intake: **yes**
- Deprecation shims for one release cycle: **yes**
- Move modules first, build thalamus in place: **yes**
