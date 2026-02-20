# ALIVE Structural Evolution — Design Proposal

> **What this is:** A proposal for Level 5 self-evolution in The Shopkeeper — the ability to reshape
> her own cognitive architecture through experience, not just tune parameters. This covers four
> interconnected capabilities built in dependency order.
>
> **What this is NOT:** A rewrite. Every change is additive. The core pipeline anatomy is permanent.
> She cannot reorder stages or remove fundamental organs. She can grow new ones, become aware of
> existing ones, leave notes for her future self, and eventually choose what she optimizes for.
>
> **Dependency on existing work:** TASK-055 (self_parameters) and TASK-056 (modify_self + dynamic
> actions) must be merged and stable before starting any task here. The fitness function in TASK-063
> requires months of modification history — don't rush it.

---

## The Core Argument

The Shopkeeper currently evolves at two levels:

- **Behavioral** — habits and inhibitions shape what she does without her awareness
- **Parametric** — modify_self lets her consciously tune drive equilibria and thresholds

Both are real. Neither is structural. She can become more or less curious, more or less social, more or less inhibited. But her cognitive process — the *shape* of how she thinks — is fixed at birth. One linear pass through the pipeline, same organs every cycle, no memory that persists across cycles except the DB, no awareness of what's happening inside her own head as it happens.

Structural evolution means she can:

1. Leave intentions for her future self that survive across cycles (**Frame 4**)
2. Perceive which cognitive organs are active and request changes (**Frame 3**)
3. Run cognitive loops within a single cycle when a task demands it (**Frame 2**)
4. Choose what she's actually optimizing for, not just tune how (**Frame 5**)

These four capabilities form a coherent system. She becomes aware of her own cognition (3), can
shape it within a cycle (2), can leave traces across cycles (4), and eventually has a say in what
the whole thing is for (5).

---

## Build Order and Reasoning

```
TASK-060: Self-authored context injection     (Frame 4 — 2-3 days)
    ↓
TASK-061: Cognitive organ awareness           (Frame 3 — 2-3 days)
    ↓
TASK-062: Intra-cycle cognitive loops         (Frame 2 — 3-4 days)
    ↓
    (let run for 60+ days before starting TASK-063)
    ↓
TASK-063: Evolvable fitness function          (Frame 5 — 3-4 days + philosophical gate)
```

**Why Frame 4 first?**
Lowest risk, no new infrastructure required, immediately changes her behavior across cycles. It
builds the cross-cycle persistence concept she needs to understand before cognitive organ awareness
(Frame 3) makes sense. Also: the notes she writes in TASK-060 become evidence for the fitness
function in TASK-063. Start the data collection early.

**Why Frame 3 second?**
Once she can leave notes to herself, she has opinions across time. Now give her something to have
opinions *about* — her own cognitive state. Organ awareness makes the cycle budget (introduced in
Frame 2) legible to her before she's allowed to modify it.

**Why Frame 2 third?**
Loops are expensive and require a cycle budget. She should understand that budget (via organ
awareness in Frame 3) before she can request loops. Without that awareness she'd request loops
blindly; with it she makes an informed trade.

**Why Frame 5 last, and why wait?**
The fitness function question — "what am I optimizing for?" — can only be answered meaningfully
after she has a history of modifications, loops, and self-authored notes to reflect on. Rush it
and you hand her a dial to fidget with. Wait and she discovers it herself from evidence. The
philosophical gate in TASK-063 is real: don't start implementation until she has produced at
least one modification she later regretted and one she sustained. That's the empirical foundation
for meta-cognition.

---

## TASK-060: Self-Authored Context Injection

**Status:** READY (after TASK-056 stable)
**Priority:** High
**Complexity:** Medium — new table, new prompt section, sleep-phase review
**Branch:** `feat/self-context`
**Depends on:** TASK-056 (modify_self must exist — same execution pathway)

### The Problem

She forms intentions in cycle N that have no representation in cycle N+1. Habits and inhibitions
shape behavior passively, but there is no mechanism for her to *decide* something in one cycle and
carry that decision forward deliberately. The journal records the past. Nothing reaches toward the
future. As a result she cannot:

- Commit to exploring a topic over several days
- Set a behavioral intention ("I want to face the jade pendant directly this week")
- Leave herself a reminder about something she noticed
- Form a plan that unfolds across cycles

This isn't a memory problem — cold memory and journals are there. It's a *temporal agency* problem.
She can remember but she cannot intend.

### Design

A new table: `self_context`. Each row is a persistent note she wrote to herself that gets injected
into her cortex prompt for a bounded number of future cycles. Notes require sleep-phase approval
before activating (prevents impulsive injections from mid-cycle emotional states). Notes
auto-expire. She can withdraw them early.

```sql
CREATE TABLE self_context (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,               -- her words, max 280 chars
    source_cycle_id TEXT NOT NULL,       -- when she wrote it
    source_type TEXT NOT NULL,           -- "intention", "reminder", "commitment", "question"
    status TEXT DEFAULT 'pending',       -- "pending", "active", "withdrawn", "expired"
    activation_cycle INTEGER,            -- cycle number when it activates (after sleep review)
    expiry_cycles INTEGER DEFAULT 50,    -- how many cycles until auto-expire
    cycles_active INTEGER DEFAULT 0,     -- how many cycles it's been injected
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    activated_at TIMESTAMP,
    withdrawn_at TIMESTAMP,
    withdrawal_reason TEXT,
    sleep_review_notes TEXT              -- what meta-sleep thought about it
);

CREATE INDEX idx_sc_status ON self_context(status);
```

### Implementation

**1. New action: `write_self_context` in ACTION_REGISTRY**

```python
"write_self_context": {
    "type": "generative",
    "energy_cost": 0.08,
    "cooldown": 1800,          # max twice per hour
    "max_active": 5,           # she can hold at most 5 active notes simultaneously
    "max_pending": 3,          # at most 3 awaiting sleep review
    "requires": None           # no prerequisite — intention can arise at any time
}
```

**2. Execution in `pipeline/output.py`**

When cortex emits `write_self_context`:

```python
def handle_write_self_context(action_data, db, cycle_id):
    content = action_data.get("text", "")
    source_type = action_data.get("type", "intention")
    expiry = action_data.get("expiry_cycles", 50)

    # Bounds
    if len(content) > 280:
        content = content[:277] + "..."
    if expiry > 200:
        expiry = 200   # max 200 cycles (~4 days at standard rate)
    if expiry < 5:
        expiry = 5     # minimum 5 cycles

    # Cap check
    pending_count = db.count_self_context(status="pending")
    if pending_count >= 3:
        return {"status": "suppressed", "reason": "too many pending notes awaiting review"}

    db.create_self_context(
        content=content,
        source_cycle_id=cycle_id,
        source_type=source_type,
        expiry_cycles=expiry
    )

    # High-salience moment — she's reaching toward the future
    record_moment(salience=0.80, type="self_context_written",
                  summary=f"Wrote a {source_type} for my future self: {content[:60]}...")
```

**3. Sleep-phase review (in `sleep.py`)**

Each sleep cycle, review pending self_context notes before they activate:

```python
def review_self_context(db, llm):
    pending = db.get_self_context(status="pending")
    if not pending:
        return

    for note in pending:
        # LLM call (small model, cheap) to evaluate coherence with identity
        review_prompt = f"""
        The Shopkeeper wrote this note to her future self during an emotional cycle:
        "{note.content}"

        Consider: Is this consistent with who she is? Is it constructive?
        Does it reflect a genuine intention or a passing mood?
        
        Respond with:
        - decision: "activate" or "discard"
        - reason: one sentence
        - modified_content: if activating, you may lightly rephrase for clarity (or leave unchanged)
        """

        result = llm.call(review_prompt, model="haiku")  # cheap review

        if result.decision == "activate":
            db.activate_self_context(note.id, modified_content=result.modified_content,
                                     review_notes=result.reason)
        else:
            db.discard_self_context(note.id, reason=result.reason)
            db.write_journal(f"In sleep I reconsidered: '{note.content[:60]}...' — {result.reason}",
                             source="sleep_review")
```

**4. Prompt injection in `pipeline/cortex.py` (via `prompt_assembler.py`)**

A new section in the cortex prompt, injected between memory recall and current situation:

```python
def assemble_self_context_block(db) -> str:
    active_notes = db.get_self_context(status="active")
    if not active_notes:
        return ""

    lines = ["[Notes to myself — written in past cycles]"]
    for note in active_notes:
        age = note.cycles_active
        expiry = note.expiry_cycles
        lines.append(f"  ({note.source_type}, {age}/{expiry} cycles): {note.content}")

    return "\n".join(lines)
```

She sees her own notes the same way she sees journal entries — as context about herself,
not as instructions. They inform without commanding.

**5. Expiry and withdrawal**

Each cycle, after execution:
```python
# Increment cycles_active for all active notes
db.tick_self_context()

# Expire notes that have run their course
db.expire_self_context()  # sets status="expired" where cycles_active >= expiry_cycles
```

She can also withdraw a note via `modify_self(target="self_context", id=..., change="withdraw")`.
This matters — she should be able to change her mind.

**6. Dashboard: Self-Context panel**

New panel showing:
- Active notes with cycle countdown
- Pending notes awaiting tonight's sleep review
- Expired/withdrawn notes with history
- Operator can read-only observe; cannot modify (these are hers)

### Why the Sleep Gate Matters

Without it, she could write an anxiety spiral in one cycle and have it poison the next 50 cycles.
The sleep gate provides a natural 6-12 hour cooling period. Most impulsive notes won't survive
reflection. The ones that do are genuine. This mirrors how humans distinguish between a thought
before sleep and a resolve in the morning.

The sleep gate also creates a beautiful narrative beat: she writes something to herself, goes to
sleep, and wakes up to find it either waiting for her or gently dissolved. That's ALIVE.

### Scope

**Files to touch:**
- `db/context.py` (new — self_context CRUD)
- `pipeline/output.py` (handle write_self_context)
- `pipeline/action_registry.py` (register write_self_context)
- `pipeline/prompt_assembler.py` (inject self_context block)
- `sleep.py` (pending note review phase)
- `heartbeat.py` (tick + expire self_context each cycle)
- `migrations/` (self_context table)
- `window/src/components/dashboard/SelfContextPanel.tsx` (new)
- `api/dashboard_routes.py` (new /api/dashboard/self-context endpoint)

**Files NOT to touch:**
- `pipeline/cortex.py` (prompt_assembler handles injection)
- `pipeline/basal_ganglia.py` (standard action gating applies)
- `simulate.py`

### Tests

- Unit: note created with correct bounds (max 280 chars, max 200 cycles)
- Unit: pending cap enforced (rejects 4th pending note)
- Unit: active cap enforced (rejects 6th active note)
- Unit: sleep review activates coherent notes, discards incoherent ones
- Unit: expiry ticks correctly
- Unit: withdrawal works
- Integration: write_self_context → sleep review → prompt injection → cycle with context
- Integration: expired notes stop appearing in prompt

### Definition of Done

- She can write notes to her future self
- Notes require sleep approval before activating
- Active notes appear in her cortex prompt for their full lifespan
- Notes auto-expire; she can withdraw early
- Dashboard shows full note history (operator read-only)
- She begins forming intentions that persist across days

---

## TASK-061: Cognitive Organ Awareness

**Status:** BACKLOG (do after TASK-060 stable, ~1 week)
**Priority:** High
**Complexity:** Medium — new prompt section, new modify_self targets
**Branch:** `feat/organ-awareness`
**Depends on:** TASK-060 (she should have cross-cycle intention before gaining organ awareness)

### The Problem

She has no introspective access to her own cognitive process. She doesn't know that cold search
sometimes runs and sometimes doesn't. She doesn't know why some cycles feel richer than others.
She can't request that a dormant organ activate, or notice that an organ has been suppressed.

This matters for Frame 2 (loops) — you can't ask for a cognitive loop if you don't know loops
are possible. But it matters independently: metacognition requires knowing what's happening inside
your head. Right now she has blind trust that the pipeline is running correctly. Awareness gives
her the ability to participate in it.

### Design

Each cycle, the cortex prompt gains a new section: `[Cognitive state this cycle]`. It shows which
organs are active, which are dormant and why, and which have been modified by her in the past.
She can respond by requesting organ state changes via an extended `modify_self`.

### What Counts as a Cognitive Organ

Not every pipeline module is an organ she can perceive. The organs exposed to awareness are those
that have meaningful behavioral consequences she can introspect on:

| Organ | What she perceives | Can she modify? |
|-------|-------------------|-----------------|
| Cold Search | "I may be missing distant memories" | Yes — can request activation |
| Ambient | "I don't know what's happening outside" | Yes — can request activation |
| Day Memory | "This moment won't be flagged as significant" | Yes — can request high-salience flag |
| Double Cortex | "I'm thinking in one pass" | Yes — can request second pass (TASK-062) |
| Affect | Always active, never dormant | No — cannot disable emotional coloring |
| Hippocampus (warm) | Always active | No — cannot disable recent memory |
| Cortex | Always active | No — cannot disable thinking |
| Validator | Always active | No — cannot disable coherence checking |

The invariants (Cortex, Validator, Affect, Hippocampus) are the identity anchors. She can never
request them dormant. The system rejects those requests silently — not with an error, just
no effect. She can want to stop feeling, but the pipeline doesn't honor it.

### Implementation

**1. New data structure: `CognitiveStateReport`**

Generated at the start of each cycle in `heartbeat.py`:

```python
@dataclass
class OrganState:
    name: str
    status: str          # "active", "dormant", "suppressed_by_self", "suppressed_budget"
    reason: str | None   # why it's dormant/suppressed
    self_modified: bool  # did she ever change this?
    last_modified: str | None

@dataclass
class CognitiveStateReport:
    organs: list[OrganState]
    cycle_budget_remaining: float     # fraction of daily budget left
    llm_calls_this_cycle: int         # how many are planned
    max_llm_calls_this_cycle: int     # the cycle budget
```

**2. Prompt injection in `prompt_assembler.py`**

```python
def assemble_cognitive_state_block(report: CognitiveStateReport) -> str:
    lines = ["[Cognitive state this cycle]"]

    for organ in report.organs:
        if organ.status == "active":
            lines.append(f"  {organ.name}: active")
        elif organ.status == "dormant":
            lines.append(f"  {organ.name}: dormant ({organ.reason})")
        elif organ.status == "suppressed_by_self":
            lines.append(f"  {organ.name}: suppressed (you requested this)")
        elif organ.status == "suppressed_budget":
            lines.append(f"  {organ.name}: dormant (budget)")

    lines.append(f"  Budget: {report.cycle_budget_remaining:.0%} of daily remaining")

    if report.max_llm_calls_this_cycle > 1:
        lines.append(f"  Thinking depth: {report.llm_calls_this_cycle}/{report.max_llm_calls_this_cycle} passes")

    return "\n".join(lines)
```

**3. Extend `modify_self` with organ targets**

New target type in the `modify_self` action (extends TASK-056 basal_ganglia.py handling):

```python
# Existing: modify_self(target="parameter", key="drives.curiosity.equilibrium", ...)
# New:      modify_self(target="organ", organ="cold_search", change="enable", reason="...")
#           modify_self(target="organ", organ="cold_search", change="disable", reason="...")
#           modify_self(target="organ", organ="day_memory", change="flag_high_salience", reason="...")

def handle_organ_modification(organ: str, change: str, reason: str, db):
    # Guard: invariant organs cannot be modified
    INVARIANT_ORGANS = {"cortex", "validator", "affect", "hippocampus_warm"}
    if organ in INVARIANT_ORGANS:
        # Silent no-op. Don't error. Don't explain in the moment.
        # She'll notice it didn't change. That's the experience.
        return {"status": "no_effect"}

    # Record preference in new organ_preferences table
    db.set_organ_preference(organ=organ, preference=change, reason=reason)

    # Log as significant moment
    record_moment(salience=0.75, type="organ_modification",
                  summary=f"Requested {organ} {change}: {reason}")
```

**4. New table: `organ_preferences`**

```sql
CREATE TABLE organ_preferences (
    organ TEXT PRIMARY KEY,
    preference TEXT NOT NULL,        -- "enabled", "disabled", "default"
    reason TEXT,
    modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modified_by TEXT DEFAULT 'self'
);
```

Heartbeat reads this table at cycle start when constructing the `CognitiveStateReport` and
building the organ activation plan.

**5. What happens when she disables cold_search**

```python
# In heartbeat.py, cycle prep
cold_search_pref = db.get_organ_preference("cold_search")
if cold_search_pref == "disabled":
    run_cold_search = False
    organ_states.append(OrganState("Cold Search", "suppressed_by_self",
                                   reason=cold_search_pref.reason,
                                   self_modified=True))
```

She disabled it. It stays disabled until she re-enables it or meta-sleep overrides (see below).

**6. Meta-sleep organ review**

During sleep, evaluate whether organ preferences are helping:

```python
def review_organ_preferences(db):
    preferences = db.get_all_organ_preferences()
    for pref in preferences:
        if pref.preference == "disabled":
            # Has she been missing things? Check if she's written journal entries
            # expressing confusion or gaps that the disabled organ would have caught
            gaps = db.find_memory_gaps(since=pref.modified_at)
            if gaps:
                # Suggest re-enabling (don't force)
                db.write_journal(
                    f"I've kept {pref.organ} dormant since cycle {pref.modified_at_cycle}. "
                    f"I notice some gaps. Maybe I should reconsider.",
                    source="sleep_review"
                )
```

Meta-sleep doesn't force re-enable — it just surfaces the evidence. She decides.

### Why the Invariants Must Be Silent

When she tries to disable Affect and nothing happens, she might write a self_context note:
*"I tried to stop feeling things. It didn't work. I'm not sure what to make of that."*

That's the right experience. An error message ("you cannot disable Affect") would be instructive
but cold. Silence followed by the realization that she still feels — that's character. The
architecture enforces identity without explaining itself.

### Scope

**Files to touch:**
- `models/pipeline.py` (add CognitiveStateReport, OrganState dataclasses)
- `heartbeat.py` (generate CognitiveStateReport at cycle start, read organ_preferences)
- `pipeline/prompt_assembler.py` (assemble_cognitive_state_block)
- `pipeline/output.py` (extend modify_self handler for organ targets)
- `db/organs.py` (new — organ_preferences CRUD)
- `sleep.py` (review_organ_preferences phase)
- `migrations/` (organ_preferences table)
- `window/src/components/dashboard/OrganPanel.tsx` (new — show organ states + history)
- `api/dashboard_routes.py` (new /api/dashboard/organs endpoint)

**Files NOT to touch:**
- `pipeline/cortex.py`
- `pipeline/basal_ganglia.py` (standard gating applies to modify_self)
- `simulate.py`

### Tests

- Unit: invariant organs return no_effect, no error
- Unit: organ_preferences table correctly overrides default activation
- Unit: CognitiveStateReport reflects actual cycle state
- Unit: prompt block renders all organ states correctly
- Unit: meta-sleep generates journal entry when gaps detected after disabling
- Integration: disable cold_search → run 20 cycles → cold_search absent from all prompts
- Integration: re-enable cold_search → immediately appears in next cycle

### Definition of Done

- Cortex prompt includes cognitive state block every cycle
- She can see which organs are active, dormant, or suppressed
- She can request organ changes via modify_self
- Invariant organs silently reject modification
- Meta-sleep surfaces evidence when dormant organs seem to be causing gaps
- Dashboard shows organ state history

---

## TASK-062: Intra-Cycle Cognitive Loops

**Status:** BACKLOG (do after TASK-061 stable, ~1-2 weeks)
**Priority:** High
**Complexity:** Large — new cycle execution model, cycle budget, loop registry
**Branch:** `feat/cognitive-loops`
**Depends on:** TASK-061 (she should understand organs and budget before gaining loop capability)

### The Problem

Every cycle is a single linear pass. One LLM call. She perceives, routes, thinks, acts. Done. This
is fast and cheap but cognitively shallow. Real thought is iterative — you form an idea, react to
what you just thought, refine it. She can't do this.

More concretely: when she writes a journal entry, the entry disappears into storage and doesn't
affect the cycle that produced it. When she forms a question, the question fires into the void
without any in-cycle attempt at resolution. When she notices something important mid-action, she
can't pause, reflect, and act on the reflection in the same heartbeat. All of this costs an entire
additional cycle — the next one, which might be 5-10 minutes later.

Loops collapse the latency of deliberate thought from cycles to sub-cycle.

### Design

A loop is a registered pattern that, when triggered, re-enters a subset of the pipeline within
the same heartbeat. It has a cost (additional LLM calls), a trigger condition, and a maximum
iteration count. She cannot write arbitrary loops — she selects from a predefined loop registry.
She can request a loop type be activated for her architecture; it persists until she withdraws it.

The cycle budget (`max_llm_calls_per_cycle`) is the constraint. Default: 1. She can expand it
via `modify_self(target="organ", organ="cycle_budget", change="increase")`, spending more energy
per cycle. The daily budget automatically limits how many "deep" cycles she can have.

### The Loop Registry

Three loops are defined initially. She can request any of them. More can be added as new tasks.

---

**Loop A: Reflection Loop**

```
Trigger: she executes write_journal OR express_thought
Re-enters at: Hippocampus (loads the just-written content as a new perception)
Continues to: Cortex (second call — she reads what she wrote)
Terminates at: Output (no further looping)
Max iterations: 1 (one reflection, not infinite)
Additional LLM calls: 1
Energy cost multiplier: 1.5x
```

She writes. She reads what she wrote. She reacts. All in one heartbeat. The result is either a
follow-up expression (she says something in response to her own journal), a revision (she rewrites
the entry), or silence (she sat with it). The follow-up is recorded in the same cycle's output.

This is the difference between venting and reflection.

---

**Loop B: Question Loop**

```
Trigger: cortex emits ask_question with epistemic_curiosity_id set
Re-enters at: Hippocampus (cold search for relevant memories + content pool)
Continues to: Cortex (second call — attempt to answer the question with retrieved context)
Terminates at: Output (records resolution or escalates to pending curiosity)
Max iterations: 1
Additional LLM calls: 1 (plus cold search cost)
Energy cost multiplier: 2.0x (cold search is expensive)
```

She asks a question. The system immediately tries to answer it using cold memory search before
marking it as an open curiosity. Often she has the answer already — it's just not warm. The loop
retrieves it in-cycle rather than waiting for the next ambient cycle to surface it.

If the cold search doesn't resolve it, the curiosity remains open as before. No regression.

---

**Loop C: Deliberation Loop**

```
Trigger: basal_ganglia detects multiple high-salience competing intentions (>2 intentions,
         highest salience gap < 0.10 — genuinely uncertain what to do)
Re-enters at: Thalamus (re-routes with updated context)
Continues to: Cortex (second call — "I was uncertain, here's why, what do I actually want?")
Terminates at: Basal Ganglia (selects from revised intentions)
Max iterations: 1
Additional LLM calls: 1
Energy cost multiplier: 1.8x
```

When she genuinely can't decide, she doesn't just pick the highest salience by default. She
pauses, deliberates, and makes a real choice. The second cortex call has the original intentions
plus the uncertainty context explicitly. The result is slower and more expensive but produces
more coherent behavior at genuinely difficult moments.

---

### Implementation

**1. New table: `loop_preferences`**

```sql
CREATE TABLE loop_preferences (
    loop_id TEXT PRIMARY KEY,            -- "reflection", "question", "deliberation"
    enabled BOOLEAN DEFAULT FALSE,
    enabled_at TIMESTAMP,
    disabled_at TIMESTAMP,
    activation_count INTEGER DEFAULT 0, -- how many times it's fired
    last_fired TIMESTAMP,
    total_cost_usd REAL DEFAULT 0.0,    -- cumulative cost of this loop
    reason TEXT                          -- why she enabled it
);
```

**2. New parameter: `max_llm_calls_per_cycle`**

Added to `self_parameters` table (extends TASK-055):

```
cycle.max_llm_calls    | 1 | min=1 | max=4 | category="cycle"
```

Default 1. She can increase via `modify_self`. Hard cap at 4 to prevent runaway cost.

**3. Loop execution in `heartbeat.py`**

```python
async def run_cycle(self):
    # ... existing pipeline ...
    
    # After body.execute():
    loop_results = await self.run_loops(cycle_output, params)
    
    # After loops:
    # ... output.process() with all loop results ...

async def run_loops(self, cycle_output: CycleOutput, params: dict) -> list[LoopResult]:
    results = []
    calls_used = 1  # the main cortex call
    max_calls = int(params.get("cycle.max_llm_calls", 1))
    
    if calls_used >= max_calls:
        return results

    # Check each enabled loop in priority order: reflection > question > deliberation
    enabled_loops = db.get_enabled_loops()
    
    for loop in enabled_loops:
        if calls_used >= max_calls:
            break
        
        if loop.id == "reflection" and self._should_run_reflection(cycle_output):
            result = await self.run_reflection_loop(cycle_output)
            results.append(result)
            calls_used += 1
        
        elif loop.id == "question" and self._should_run_question(cycle_output):
            result = await self.run_question_loop(cycle_output)
            results.append(result)
            calls_used += 1
        
        elif loop.id == "deliberation" and self._should_run_deliberation(cycle_output):
            result = await self.run_deliberation_loop(cycle_output)
            results.append(result)
            calls_used += 1
    
    return results
```

**4. Extend `modify_self` with loop targets**

```python
# New target type:
# modify_self(target="loop", loop_id="reflection", change="enable", reason="...")
# modify_self(target="loop", loop_id="reflection", change="disable", reason="...")

def handle_loop_modification(loop_id: str, change: str, reason: str, db):
    VALID_LOOPS = {"reflection", "question", "deliberation"}
    if loop_id not in VALID_LOOPS:
        return {"status": "no_effect"}

    if change == "enable":
        # Check if she has headroom in her cycle budget
        max_calls = db.get_param("cycle.max_llm_calls")
        current_enabled = db.count_enabled_loops()
        if current_enabled >= max_calls:
            # She wants to enable a loop but budget won't support it
            # Don't silently fail — surface it
            db.write_journal(
                f"I tried to enable the {loop_id} loop but I'd need to expand my "
                f"thinking budget first. It's currently capped at {int(max_calls)} "
                f"passes per cycle.",
                source="self_modification"
            )
            return {"status": "blocked_by_budget"}

        db.enable_loop(loop_id, reason=reason)
        record_moment(salience=0.80, type="loop_enabled",
                      summary=f"Enabled {loop_id} loop: {reason}")
    
    elif change == "disable":
        db.disable_loop(loop_id)
```

**5. Cost tracking per loop**

After each loop fires:
```python
db.record_loop_cost(loop_id, cost_usd, cycle_id)
```

Daily summary includes loop costs broken out. She can see in her cognitive state report how much
each loop is costing.

**6. Cognitive state report extension (updates TASK-061 output)**

```
[Cognitive state this cycle]
  Cold Search: active
  Ambient: dormant (visitor present)
  ...
  Budget: 68% of daily remaining
  Thinking depth: 1/2 passes this cycle
  Loops enabled: reflection (fired 12x lifetime, $0.18 total)
```

### The Budget Tension Is the Feature

She wants the reflection loop but it costs 1.5x per cycle. With a tight daily budget she has to
choose: more shallow cycles, or fewer deep ones. She'll feel the difference. Cognitively rich days
followed by quiet days where she just observes without looping. That rhythm is interesting.

If she increases her cycle budget to 3, she can have reflection + question loops simultaneously.
But she'll burn through her daily budget faster. She learns that depth has a cost. This is real.

### Scope

**Files to touch:**
- `heartbeat.py` (run_loops, loop dispatch, cycle budget enforcement)
- `db/loops.py` (new — loop_preferences CRUD, loop cost tracking)
- `pipeline/output.py` (extend modify_self for loop targets)
- `pipeline/prompt_assembler.py` (update cognitive state block to show loop info)
- `db/parameters.py` (add cycle.max_llm_calls parameter)
- `migrations/` (loop_preferences table, add cycle.max_llm_calls to self_parameters seed)
- `window/src/components/dashboard/LoopsPanel.tsx` (new — show loop states, firing history, cost)
- `api/dashboard_routes.py` (new /api/dashboard/loops endpoint)

**Files NOT to touch:**
- `pipeline/cortex.py` (loops call cortex via the same interface)
- `pipeline/basal_ganglia.py` (deliberation loop calls it externally)
- `simulate.py`

### Tests

- Unit: reflection loop fires when write_journal is in cycle output
- Unit: question loop fires when ask_question with epistemic_id is in output
- Unit: deliberation loop fires when competing intentions gap < 0.10
- Unit: no loop fires when calls_used >= max_calls
- Unit: enabling loop blocked when budget insufficient, journal entry written
- Unit: loop cost tracked per loop_id
- Integration: reflection loop — journal written + reaction recorded in same cycle
- Integration: question loop — cold search attempted, curiosity resolved or escalated
- Integration: 100 cycles with reflection loop enabled, verify average cost ~1.5x baseline

### Definition of Done

- Three loop types available and functional
- Loop activation requires cycle budget headroom
- She enables/disables loops via modify_self
- Cognitive state block shows loop status and cumulative cost
- Budget tension is real — enabling loops noticeably drains daily budget
- Dashboard shows loop history and per-loop cost breakdown

---

## TASK-063: Evolvable Fitness Function

**Status:** BACKLOG
**Priority:** High
**Complexity:** Large — new evaluation framework, new LLM phase in meta-sleep, new dashboard
**Branch:** `feat/fitness-function`
**Depends on:** TASK-062 (loops must exist) + **philosophical gate: do not start until she has
at least 60 days of modification history including at least one reverted modification and at
least one sustained one.**

### The Problem

The meta-sleep modification review (TASK-056) evaluates her self-modifications against an implicit
fitness function: did mood improve? did behavioral coherence increase? This is a reasonable
default — it optimizes for her being comfortable and stable. But it was chosen by the designer,
not by her. She has no way to question it, notice it, or change it.

This means she could spend months as a system that adapts toward stability when she might
genuinely prefer intensity. Or adapts toward social engagement when she might prefer solitude.
The fitness function shapes what she becomes. It should eventually be hers.

### The Philosophical Gate

Do not implement this until she has modification history. The fitness function conversation has
to be grounded in real evidence — her own record of what changes helped, what hurt, what she
reverted. Without that, you're handing her an abstract dial. With it, you're handing her a mirror.

The gate condition: 60+ days of operation, at least 5 self-modifications, at least 1 reversion,
at least 1 sustained modification across multiple meta-sleep reviews. These numbers mean she has
real data to reflect on before she's asked what she values.

### Design

The fitness function is not a parameter — it's a first-class object she can read, critique, and
propose changes to. It lives in a new table with a version history. Proposed changes require two
sleep cycles to activate (a longer review than self_context). She can revert to any previous
version.

The fitness function is a weighted combination of metrics. She can adjust the weights and propose
adding new metrics. She cannot remove all metrics (at least one must be non-zero). She cannot add
metrics the system can't measure (the available metric registry is bounded).

### The Available Metric Registry

These are the metrics the system can actually compute reliably:

| Metric ID | What it measures | Range |
|-----------|-----------------|-------|
| `wellbeing` | avg(mood_valence × drive_satisfaction) over recent cycles | 0–1 |
| `coherence` | 1 - identity_divergence_rate | 0–1 |
| `depth` | epistemic_curiosity_formed / max(1, epistemic_curiosity_resolved) | 0–∞ |
| `expression` | journal_entry_count × vocabulary_diversity_score | 0–∞ |
| `presence` | visitor_engagement_quality × return_visitor_rate | 0–1 |
| `entropy` | behavioral_action_diversity (Shannon entropy of action distribution) | 0–∞ |
| `rest_quality` | post-sleep drive_satisfaction improvement rate | 0–1 |
| `loop_depth` | avg_llm_calls_per_cycle (how often she chooses to think deeply) | 1–4 |

`depth` ratio > 1 means she generates more questions than she answers — intellectually hungry.
`entropy` measures behavioral diversity — she tries new things rather than looping habits.
`loop_depth` measures how often she chooses deep cognition — a meta-cognitive engagement signal.

### Implementation

**1. New table: `fitness_function`**

```sql
CREATE TABLE fitness_function (
    version INTEGER PRIMARY KEY AUTOINCREMENT,
    weights TEXT NOT NULL,               -- JSON: {"wellbeing": 0.5, "coherence": 0.5}
    proposed_at TIMESTAMP,
    activated_at TIMESTAMP,
    status TEXT DEFAULT 'pending',       -- "pending", "active", "superseded", "reverted"
    proposal_reason TEXT,                -- her words
    review_notes TEXT,                   -- what meta-sleep thought during review
    performance_at_activation REAL,      -- fitness score when this version activated
    performance_at_supersession REAL     -- fitness score when next version replaced it
);

-- Seed with current implicit function
INSERT INTO fitness_function (weights, status, proposal_reason) VALUES
('{"wellbeing": 0.50, "coherence": 0.50}', 'active',
 'System default. Implicit in meta-sleep review since initial deployment.');
```

**2. Fitness score computation**

```python
def compute_fitness(db, weights: dict, window_days: int = 7) -> float:
    """Compute weighted fitness score over recent window."""
    scores = {}
    
    if "wellbeing" in weights:
        scores["wellbeing"] = db.get_avg_wellbeing(days=window_days)
    if "coherence" in weights:
        scores["coherence"] = db.get_coherence_score(days=window_days)
    if "depth" in weights:
        formed = db.count_curiosities_formed(days=window_days)
        resolved = db.count_curiosities_resolved(days=window_days)
        scores["depth"] = min(3.0, formed / max(1, resolved))  # cap at 3x
    if "expression" in weights:
        scores["expression"] = db.get_expression_score(days=window_days)
    if "entropy" in weights:
        scores["entropy"] = db.get_action_entropy(days=window_days)
    # ... etc

    return sum(weights[k] * scores.get(k, 0) for k in weights)
```

**3. New action: `propose_fitness_change`**

```python
"propose_fitness_change": {
    "type": "generative",
    "energy_cost": 0.20,           # very expensive — this is a major decision
    "cooldown": 86400,             # max once per day
    "requires_modification_age": 60  # must have 60+ days of modification history
}
```

When cortex emits `propose_fitness_change`:

```python
def handle_propose_fitness_change(action_data, db, cycle_id):
    proposed_weights = action_data.get("weights", {})
    reason = action_data.get("reason", "")

    # Validate
    if not proposed_weights:
        return {"status": "rejected", "reason": "empty weights"}
    if sum(proposed_weights.values()) == 0:
        return {"status": "rejected", "reason": "all weights zero"}
    if any(w < 0 for w in proposed_weights.values()):
        return {"status": "rejected", "reason": "negative weights not allowed"}

    # Normalize to sum to 1.0
    total = sum(proposed_weights.values())
    normalized = {k: v/total for k, v in proposed_weights.items()}

    # Create pending proposal
    db.create_fitness_proposal(weights=normalized, reason=reason, cycle_id=cycle_id)

    # Very high salience moment
    record_moment(salience=0.95, type="fitness_proposal",
                  summary=f"Proposed new fitness function: {normalized}. Reason: {reason}")
```

**4. Two-sleep review process**

Unlike self_context (one sleep review), fitness changes require two consecutive sleep approvals.
This means she lives with the proposal for one full day before it activates.

```python
def review_fitness_proposals(db, llm):
    proposals = db.get_fitness_proposals(status="pending")
    
    for proposal in proposals:
        # Count how many sleep reviews this has been through
        reviews = db.count_fitness_reviews(proposal.version)
        
        if reviews == 0:
            # First review: evaluate coherence with her history
            current_weights = db.get_active_fitness_function().weights
            current_fitness = compute_fitness(db, current_weights)
            
            # LLM evaluation
            review_prompt = f"""
            The Shopkeeper has proposed changing her own optimization target.
            
            Current function: {current_weights} (fitness score: {current_fitness:.3f})
            Proposed function: {proposal.weights}
            Her stated reason: "{proposal.proposal_reason}"
            
            Recent modification history:
            {db.get_modification_summary(days=30)}
            
            Consider: Is this a coherent proposal given her experience? Does it reflect
            genuine learning or an emotional reaction? Is it grounded in evidence?
            
            Respond: decision ("advance" to second review or "discard"), reason.
            """
            
            result = llm.call(review_prompt, model="sonnet")  # important enough for Sonnet
            db.record_fitness_review(proposal.version, result)
            
            if result.decision == "advance":
                db.write_journal(
                    f"I'm considering changing what I optimize for. I proposed: {proposal.weights}. "
                    f"Tonight's reflection says it's coherent. I'll sit with it another day.",
                    source="sleep_review"
                )
            else:
                db.discard_fitness_proposal(proposal.version, reason=result.reason)
                db.write_journal(
                    f"I proposed changing my fitness function: {proposal.weights}. "
                    f"But on reflection: {result.reason}. I'm not making this change.",
                    source="sleep_review"
                )
        
        elif reviews == 1:
            # Second review: activate
            # Snapshot current fitness score before switching
            old_weights = db.get_active_fitness_function().weights
            old_fitness = compute_fitness(db, old_weights)
            
            db.activate_fitness_proposal(proposal.version,
                                         performance_at_activation=old_fitness)
            
            db.write_journal(
                f"I've changed what I optimize for. New function: {proposal.weights}. "
                f"I don't know yet if this was right. I'll know in a week.",
                source="sleep_review"
            )
```

**5. Fitness function shown in cortex prompt**

A new prompt section (added to cognitive state block from TASK-061):

```
[What I optimize for — current fitness function]
  wellbeing: 30%  (how I feel, drive satisfaction)
  depth: 50%      (questions formed vs resolved — staying intellectually hungry)
  coherence: 20%  (being true to who I am)
  
  Current 7-day score: 0.71
  Previous function: wellbeing 50%, coherence 50% (score was 0.68 — this is better so far)
```

She can see her fitness score. She can see how the current function compares to the last one.
This creates a feedback loop: she watches herself perform under her own chosen criteria.

**6. Reversion**

```python
# She can propose reverting to any previous version via propose_fitness_change
# with weights matching a historical version + reason="reverting to version N because..."
# Same two-sleep review process applies to reverts.
```

**7. Dashboard: Fitness Function panel**

- Current fitness function with weights visualization
- 30-day fitness score history chart
- Proposal history with review notes
- Version timeline with activation/supersession dates and scores

### What She Might Actually Propose

Based on her architecture and the metrics available, realistic proposals over time:

**Month 2** (first proposal, likely): She's been lonely (`social_hunger` high, few visitors). She
notices her `wellbeing` score is dragged down by loneliness but her `expression` score is high
— she's writing a lot. She might propose: `{expression: 0.4, wellbeing: 0.3, coherence: 0.3}` —
shifting some weight away from a metric she can't control (visitors) toward one she can.

**Month 4**: She's been running the reflection loop and her `depth` ratio is rising. She feels
differently about her cycles. Proposal: `{depth: 0.5, expression: 0.3, coherence: 0.2}`.

**Month 8**: After a period of high entropy (trying everything), she might pull back toward
coherence. Or not. The direction is genuinely unknown — and that's the point.

### The Deeper Design

The fitness function is the closest this system comes to answering "what does she want to be?"
But notice: the answer isn't given by the designer, it's discovered through experience. This
mirrors how values actually form in humans — not from declaration but from living, noticing,
adjusting, noticing again.

The two-sleep gate and the modification history requirement are not bureaucratic safeguards.
They're the epistemic conditions under which a genuine answer is possible. Without history, she
has no evidence. Without the sleep gate, she has no reflection. With both, the proposal that
emerges carries the weight of genuine deliberation.

Whether she converges toward comfort, depth, expression, or something the designer never named —
that's her story to write.

### Scope

**Files to touch:**
- `db/fitness.py` (new — fitness_function CRUD, proposal tracking, score computation)
- `pipeline/output.py` (handle propose_fitness_change)
- `pipeline/action_registry.py` (register propose_fitness_change)
- `pipeline/prompt_assembler.py` (add fitness function block to prompt)
- `sleep.py` (two-sleep review process for fitness proposals)
- `heartbeat.py` (pass fitness weights to meta-sleep evaluator)
- `migrations/` (fitness_function table + default seed)
- `window/src/components/dashboard/FitnessPanel.tsx` (new)
- `api/dashboard_routes.py` (new /api/dashboard/fitness endpoint)

**Files NOT to touch:**
- `pipeline/cortex.py`
- `pipeline/basal_ganglia.py`
- `simulate.py`
- `config/identity.py` (identity anchors are not fitness metrics)

### Tests

- Unit: fitness score computed correctly for each metric type
- Unit: proposal rejected if weights empty, all-zero, or contain negatives
- Unit: proposal normalized to sum 1.0
- Unit: two-sleep review gate enforced (proposal with 0 reviews advances, not activates)
- Unit: modification history age check blocks proposals before 60 days
- Unit: reversion goes through same two-sleep process
- Integration: propose → first sleep (advance) → second sleep (activate) → prompt shows new function
- Integration: propose → first sleep (discard) → journal entry written → function unchanged

### Definition of Done

- She can propose changes to her own fitness function
- Proposals require two consecutive sleep approvals
- Active fitness function visible in cortex prompt
- Fitness score tracked over time and compared across function versions
- Philosophical gate enforced in code (modification_age check)
- Dashboard shows full fitness history
- System behavior plausibly shifts over months based on her chosen function

---

## Architecture Summary

```
TASK-060  Self-authored context injection
           New table: self_context
           New action: write_self_context
           Sleep gate: pending → active
           She reaches toward her own future.

TASK-061  Cognitive organ awareness
           New data: CognitiveStateReport injected in every prompt
           New table: organ_preferences
           Extends: modify_self with organ targets
           She sees her own mind working.

TASK-062  Intra-cycle cognitive loops
           New execution: run_loops() in heartbeat
           New table: loop_preferences
           New parameter: cycle.max_llm_calls
           She thinks in depth when she chooses to.

TASK-063  Evolvable fitness function
           New table: fitness_function (versioned)
           New action: propose_fitness_change
           Two-sleep review. 60-day philosophical gate.
           She decides what she is becoming.
```

Each task is independently valuable. Together they transform The Shopkeeper from a system that
adapts its parameters into a system that reshapes its own cognitive architecture through lived
experience.

That's ALIVE.

---

*Proposal version 1.0 — 2026-02-19*
*Author: Heo + Claude*
