# THE BODY — Pipeline Stage Spec (v2)

## For: Claude Code
## Revision: Split brain-side decision logic from body-side execution
## Supersedes: body-spec.md (v1)

---

## 1. REVISED PIPELINE

```
Input → Sensor → Deep Brain → Cortex → Validator → Basal Ganglia → Body → Output
         │          │            │          │              │            │        │
       perceive    feel        think     format?     select/inhibit   do     result
                                          (brain)       (brain)     (body)
```

**Everything left of the arrow into Body = brain.** Thinking, deciding, filtering, inhibiting.
**Body = muscles.** Receiving commands, checking physical capability, executing, reporting back.

---

## 2. THE THREE STAGES

### 2.1 Validator (brain — unchanged from current)

Already exists. Format checks on Cortex output. Schema validation. Engagement rules.

Position: immediately after Cortex.
Question it answers: **"Is this well-formed?"**

Not changing this. It stays where it is, does what it does. The only update: it now validates the new `intentions[]` schema once Phase 2 ships.

### 2.2 Basal Ganglia (brain — new stage)

**File:** `pipeline/basal_ganglia.py`

Position: after Validator, before Body.
Question it answers: **"Which of these intentions should fire, and which should be suppressed?"**

This is where all the interesting decision logic lives:
- Action selection (multiple intentions → ranked execution plan)
- Inhibition (learned behavioral constraints)
- Habit shortcuts (strong habits bypass Cortex entirely)
- Energy gating (too tired to do this?)
- Cooldown enforcement

It receives validated intentions from Cortex. It outputs a **motor plan** — an ordered list of approved actions plus a log of what was suppressed and why.

```python
@dataclass
class MotorPlan:
    """The basal ganglia's output. Handed to Body for execution."""
    actions: list[ActionDecision]       # approved, ordered by priority
    suppressed: list[ActionDecision]    # held back, with reasons
    habit_fired: bool                   # True if this cycle skipped Cortex
    energy_budget: float                # remaining energy after gating

@dataclass
class ActionDecision:
    action: str
    content: str
    target: Optional[str]
    impulse: float                # from Cortex (or habit strength)
    priority: float               # after basal ganglia adjustments
    status: str                   # 'approved' | 'suppressed' | 'incapable' | 'deferred'
    suppression_reason: Optional[str]
    source: str                   # 'cortex' | 'habit'
```

#### Selection Gates (in order)

```python
async def select_actions(
    intentions: list[dict],
    drives: DrivesState,
    engagement_state: str,
    cycle_context: dict,
    db_conn
) -> MotorPlan:
    """
    Brain-side action selection. Decides what fires and what doesn't.
    Body never sees suppressed actions — only approved ones.
    """
    decisions = []

    for intent in intentions:
        action_name = intent['action']
        decision = ActionDecision(
            action=action_name,
            content=intent.get('content', ''),
            target=intent.get('target'),
            impulse=intent.get('impulse', 0.5),
            priority=0.0,
            status='pending',
            suppression_reason=None,
            source='cortex'
        )

        # Gate 1: Does she know this action exists?
        if action_name not in ACTION_REGISTRY:
            decision.status = 'incapable'
            decision.suppression_reason = f'Unknown action: {action_name}'
            decisions.append(decision)
            continue

        capability = ACTION_REGISTRY[action_name]

        # Gate 2: Is it enabled? (physical capability — but checked here
        # because brain knows what body can do, like you know you can't fly)
        if not capability.enabled:
            decision.status = 'incapable'
            decision.suppression_reason = 'Cannot do this yet'
            decisions.append(decision)
            continue

        # Gate 3: Prerequisites met?
        prereq_check = check_prerequisites(capability.requires, cycle_context)
        if not prereq_check.passed:
            decision.status = 'suppressed'
            decision.suppression_reason = f'Not possible right now: {prereq_check.failed}'
            decisions.append(decision)
            continue

        # Gate 4: Cooldown
        if capability.last_used and capability.cooldown_seconds > 0:
            elapsed = (datetime.now() - capability.last_used).total_seconds()
            if elapsed < capability.cooldown_seconds:
                decision.status = 'deferred'
                decision.suppression_reason = f'Too soon ({int(capability.cooldown_seconds - elapsed)}s)'
                decisions.append(decision)
                continue

        # Gate 5: Energy
        if drives.energy < capability.energy_cost:
            decision.status = 'suppressed'
            decision.suppression_reason = f'Too tired (need {capability.energy_cost}, have {drives.energy:.2f})'
            decisions.append(decision)
            continue

        # Gate 6: Inhibition (learned — the interesting one)
        inhibition = await check_inhibition(action_name, intent, cycle_context, db_conn)
        if inhibition.suppress:
            decision.status = 'suppressed'
            decision.suppression_reason = inhibition.reason
            decisions.append(decision)
            continue

        # Passed all gates
        decision.priority = calculate_priority(intent, drives, capability)
        decision.status = 'approved'
        decisions.append(decision)

    approved = [d for d in decisions if d.status == 'approved']
    approved.sort(key=lambda d: d.priority, reverse=True)
    approved = enforce_limits(approved)  # max_per_cycle per action type

    suppressed = [d for d in decisions if d.status != 'approved']

    return MotorPlan(
        actions=approved,
        suppressed=suppressed,
        habit_fired=False,
        energy_budget=drives.energy
    )
```

#### Priority Calculation

```python
def calculate_priority(intent: dict, drives: DrivesState, cap: ActionCapability) -> float:
    base = intent.get('impulse', 0.5)

    # Social drive boosts visitor-directed actions
    if intent.get('target') == 'visitor':
        base += drives.social_need * 0.2

    # Low energy dampens costly actions
    if cap.energy_cost > 0.1 and drives.energy < 0.3:
        base *= 0.6

    # Habit bonus
    habit_strength = get_habit_strength(cap.name)
    base += habit_strength * 0.1

    return min(base, 1.0)
```

#### Inhibition System

Learned constraints. Forms from experience, not rules.

```python
@dataclass
class InhibitionCheck:
    suppress: bool
    reason: Optional[str]
    inhibition_id: Optional[str]

async def check_inhibition(
    action: str,
    intent: dict,
    context: dict,
    db_conn
) -> InhibitionCheck:
    """
    Check if any learned inhibition applies to this action in this context.
    Pure DB lookup — no LLM call.
    """
    inhibitions = await get_inhibitions_for_action(action, db_conn)

    for inhib in inhibitions:
        if inhib.strength < 0.2:
            continue  # too weak to matter

        pattern = json.loads(inhib.pattern)
        if matches_pattern(pattern, context):
            # Probabilistic — stronger inhibitions suppress more reliably
            if random.random() < inhib.strength:
                # Update tracking
                inhib.last_triggered = datetime.now()
                inhib.trigger_count += 1
                await save_inhibition(inhib, db_conn)

                return InhibitionCheck(
                    suppress=True,
                    reason=inhib.reason,
                    inhibition_id=inhib.id
                )

    return InhibitionCheck(suppress=False, reason=None, inhibition_id=None)
```

**How inhibitions form (runs in Output processing, not in Basal Ganglia):**

Two signal sources:

**External signals:**
- Visitor left within 1 turn of her action
- No response to something she said
- Post on X got zero engagement

**Internal signals (from Cortex feelings output):**
- Pattern match on feelings: "I shouldn't have", "that felt wrong", "I regret", "too much", "they seemed uncomfortable"
- These are Cortex already telling us something went badly — no extra LLM call

```python
NEGATIVE_FEELING_PATTERNS = [
    r"shouldn't have",
    r"regret",
    r"too much",
    r"wrong thing to say",
    r"uncomfortable",
    r"pushed too hard",
    r"felt wrong",
    r"wished I hadn't",
]

async def detect_negative_signal(
    action_result: ActionResult,
    cortex_feelings: str,
    cycle_context: dict,
    db_conn
) -> bool:
    """Check for negative signals from both external and internal sources."""

    # External: visitor left quickly
    if action_result.action == 'speak' and cycle_context.get('visitor_left_within', 999) <= 1:
        return True

    # Internal: Cortex expressed regret in feelings
    for pattern in NEGATIVE_FEELING_PATTERNS:
        if re.search(pattern, cortex_feelings, re.IGNORECASE):
            return True

    return False
```

**Inhibition formation:**

```python
async def maybe_form_inhibition(
    action_taken: ActionDecision,
    negative: bool,
    positive: bool,
    cortex_feelings: str,
    cycle_context: dict,
    db_conn
):
    if negative:
        existing = await find_matching_inhibition(action_taken, db_conn)
        if existing:
            existing.strength = min(existing.strength + 0.15, 1.0)
            existing.trigger_count += 1
            await save_inhibition(existing, db_conn)
        else:
            await create_inhibition(
                action=action_taken.action,
                pattern=extract_pattern(action_taken, cycle_context),
                # Reason lives as structured data. Cortex narrates it
                # in her journal naturally — no template needed.
                reason=extract_inhibition_seed(action_taken, cycle_context),
                strength=0.3,
                db_conn=db_conn
            )

    elif positive:
        existing = await find_matching_inhibition(action_taken, db_conn)
        if existing:
            existing.strength = max(existing.strength - 0.1, 0.0)
            if existing.strength < 0.05:
                await delete_inhibition(existing.id, db_conn)
            else:
                await save_inhibition(existing, db_conn)
```

**Note on inhibition reasons:** v1 used templates ("They left quickly after I {action}"). Bad call. The inhibition record stores a **seed** — structured data about what happened. When she journals, Cortex has access to recent inhibitions and narrates them in her voice. The system tracks the *what*. Cortex expresses the *why*. Zero extra LLM calls, authentic voice.

```python
def extract_inhibition_seed(action: ActionDecision, context: dict) -> str:
    """Structured seed, not a narrative. Cortex turns this into her words later."""
    return json.dumps({
        'action': action.action,
        'target': action.target,
        'context_mode': context.get('mode'),
        'visitor_turn': context.get('turn_count'),
        'trigger': 'visitor_left_early' if context.get('visitor_left_within', 999) <= 1
                   else 'self_assessment',
    })
```

#### Habit System

Repeated patterns crystallize into reflexes.

**Strength curve — fast early, slow later:**

```python
def calculate_new_strength(current: float, repetition: int) -> float:
    """
    Nonlinear growth.
    0 → 0.4 in ~10 reps (fast — early pattern recognition)
    0.4 → 0.6 in ~15 more (slowing)
    0.6 → 0.8 in ~25 more (slow — habit is cementing)
    """
    if current < 0.4:
        return min(current + 0.04, 1.0)   # fast
    elif current < 0.6:
        return min(current + 0.015, 1.0)  # medium
    else:
        return min(current + 0.008, 1.0)  # slow

# Auto-fire threshold: 0.6 (not 0.8 — reachable in first week)
HABIT_AUTO_FIRE_THRESHOLD = 0.6
```

**Habit-driven cycles — enter pipeline BEFORE Cortex:**

```python
async def check_habits(drives: DrivesState, context: dict, db_conn) -> Optional[MotorPlan]:
    """
    Called in heartbeat BEFORE the Cortex call.
    If a strong habit matches, returns a MotorPlan directly.
    Cortex is skipped entirely — this is reflex, not thought.
    """
    habits = await get_matching_habits(drives, context, db_conn)

    for habit in habits:
        if habit.strength >= HABIT_AUTO_FIRE_THRESHOLD:
            if random.random() < habit.strength:
                return MotorPlan(
                    actions=[ActionDecision(
                        action=habit.action,
                        content=habit.default_content or '',
                        target=None,
                        impulse=habit.strength,
                        priority=habit.strength,
                        status='approved',
                        suppression_reason=None,
                        source='habit'
                    )],
                    suppressed=[],
                    habit_fired=True,
                    energy_budget=drives.energy
                )

    return None  # No habit matched — proceed to Cortex as normal
```

**Habit tracking (runs in Output processing):**

```python
async def track_action_pattern(
    action: ActionDecision,
    drives: DrivesState,
    context: dict,
    db_conn
):
    """After every executed action, check if a habit should form or strengthen."""
    trigger = build_trigger_context(drives, context)
    existing = await find_matching_habit(action.action, trigger, db_conn)

    if existing:
        existing.repetition_count += 1
        existing.strength = calculate_new_strength(existing.strength, existing.repetition_count)
        existing.last_fired = datetime.now()
        if action.content:
            existing.default_content = action.content  # most recent version
        await save_habit(existing, db_conn)
    else:
        # First occurrence — don't create habit yet
        # Second occurrence of same action + similar context — create at 0.1
        recent_similar = await count_recent_similar_actions(
            action.action, trigger, hours=48, db_conn=db_conn
        )
        if recent_similar >= 1:  # this is the second time
            await create_habit(
                action=action.action,
                trigger_context=json.dumps(trigger),
                default_content=action.content,
                strength=0.1,
                db_conn=db_conn
            )
```

**Trigger context — what conditions define "same situation":**

```python
def build_trigger_context(drives: DrivesState, context: dict) -> dict:
    """
    Coarse-grained context for habit matching.
    Too specific = habits never form. Too broad = meaningless habits.
    """
    return {
        'energy_band': 'low' if drives.energy < 0.3 else 'mid' if drives.energy < 0.7 else 'high',
        'mood_band': 'negative' if drives.mood < -0.3 else 'neutral' if drives.mood < 0.3 else 'positive',
        'mode': context.get('mode'),                    # idle, engage, etc.
        'time_band': context.get('time_band'),          # morning, afternoon, evening, night
        'visitor_present': context.get('visitor_present', False),
    }
```

---

### 2.3 Body (new stage — pure execution)

**File:** `pipeline/body.py`

Position: after Basal Ganglia.
Question it answers: **"Can I physically do this, and what happened when I tried?"**

The Body is thin. It receives approved actions from the MotorPlan and executes them. It does NOT decide. It does NOT inhibit. It does NOT prioritize. All of that already happened in the brain.

The only checks the Body performs are **physical capability checks** — is the API reachable, is the wallet connected, does the file exist. These are "my hand is broken" checks, not "should I punch" checks.

```python
@dataclass
class ActionResult:
    action: str
    success: bool
    content: Optional[str]          # what was actually output
    error: Optional[str]
    side_effects: list[str]         # ['visitor_message_sent', 'journal_entry_created']
    timestamp: datetime

@dataclass
class BodyOutput:
    executed: list[ActionResult]
    energy_spent: float
    
    def has_visible_action(self) -> bool:
        visible = {'speak', 'arrange_shelf', 'post_x'}
        return any(r.action in visible and r.success for r in self.executed)


async def execute(motor_plan: MotorPlan, drives: DrivesState, db_conn) -> BodyOutput:
    """
    Pure execution. No decisions. No filtering.
    The MotorPlan says do it, we do it.
    """
    results = []
    energy_spent = 0.0

    for action in motor_plan.actions:
        executor = ACTION_EXECUTORS.get(action.action)

        if executor is None:
            results.append(ActionResult(
                action=action.action,
                success=False,
                content=None,
                error=f'No executor registered for: {action.action}',
                side_effects=[],
                timestamp=datetime.now()
            ))
            continue

        # Physical capability check (API up? wallet connected? etc.)
        capability = ACTION_REGISTRY[action.action]
        physical_check = await check_physical(capability, action)
        if not physical_check.ready:
            results.append(ActionResult(
                action=action.action,
                success=False,
                content=None,
                error=f'Physical check failed: {physical_check.reason}',
                side_effects=[],
                timestamp=datetime.now()
            ))
            continue

        try:
            result = await executor(action, drives, db_conn)
            results.append(result)
            energy_spent += capability.energy_cost

            # Update last_used on the capability
            capability.last_used = datetime.now()

        except Exception as e:
            results.append(ActionResult(
                action=action.action,
                success=False,
                content=None,
                error=str(e),
                side_effects=[],
                timestamp=datetime.now()
            ))

    return BodyOutput(
        executed=results,
        energy_spent=energy_spent
    )
```

#### Physical Capability Checks

```python
@dataclass
class PhysicalCheck:
    ready: bool
    reason: Optional[str]

async def check_physical(capability: ActionCapability, action: ActionDecision) -> PhysicalCheck:
    """
    Is the body physically able to execute this?
    Not 'should she' — 'can she'.
    """
    checks = {
        'browse_web': check_internet_available,
        'post_x': check_x_api_configured,
        'make_purchase': check_wallet_connected,
        'send_message': check_messaging_configured,
        'watch_video': check_video_api_available,
    }

    checker = checks.get(action.action)
    if checker is None:
        return PhysicalCheck(ready=True, reason=None)  # no special check needed

    return await checker(action)


async def check_internet_available(action: ActionDecision) -> PhysicalCheck:
    """Can she reach the internet?"""
    try:
        # Simple connectivity check
        async with aiohttp.ClientSession() as session:
            async with session.head('https://httpbin.org/status/200', timeout=5) as resp:
                return PhysicalCheck(ready=True, reason=None)
    except:
        return PhysicalCheck(ready=False, reason='No internet connection')

async def check_x_api_configured(action: ActionDecision) -> PhysicalCheck:
    """Are X API credentials set?"""
    if not os.environ.get('X_API_KEY'):
        return PhysicalCheck(ready=False, reason='X API not configured')
    return PhysicalCheck(ready=True, reason=None)

async def check_wallet_connected(action: ActionDecision) -> PhysicalCheck:
    """Is the PicoClaw wallet reachable?"""
    if not os.environ.get('PICOCLAW_ENDPOINT'):
        return PhysicalCheck(ready=False, reason='Wallet not connected')
    return PhysicalCheck(ready=True, reason=None)
```

#### Action Executors

Same functions as the old Executor, now registered in the Body.

```python
ACTION_EXECUTORS: dict[str, Callable] = {
    # === EXISTING (migrated from executor.py) ===
    'speak':            execute_speak,
    'journal_write':    execute_journal_write,
    'arrange_shelf':    execute_arrange_shelf,
    'express_thought':  execute_express_thought,
    'end_engagement':   execute_end_engagement,

    # === FUTURE (stubs until enabled) ===
    'browse_web':       execute_browse_web,
    'post_x':           execute_post_x,
    'watch_video':      execute_watch_video,
    'search_marketplace': execute_search_marketplace,
    'make_purchase':    execute_make_purchase,
    'send_message':     execute_send_message,
}
```

Each executor is a pure function: receives an ActionDecision, does the thing, returns an ActionResult. No decision logic inside.

---

## 3. ACTION REGISTRY

Shared between Basal Ganglia (for gating) and Body (for execution). Lives in its own file.

**File:** `pipeline/action_registry.py`

```python
@dataclass
class ActionCapability:
    name: str
    enabled: bool
    energy_cost: float
    cooldown_seconds: int
    last_used: Optional[datetime]
    max_per_cycle: int
    requires: list[str]
    description: str

ACTION_REGISTRY: dict[str, ActionCapability] = {
    'speak': ActionCapability(
        name='speak',
        enabled=True,
        energy_cost=0.15,
        cooldown_seconds=0,
        max_per_cycle=1,
        requires=['visitor_present'],
        description='Speak to the visitor'
    ),
    'journal_write': ActionCapability(
        name='journal_write',
        enabled=True,
        energy_cost=0.05,
        cooldown_seconds=300,
        max_per_cycle=1,
        requires=[],
        description='Write in journal'
    ),
    'arrange_shelf': ActionCapability(
        name='arrange_shelf',
        enabled=True,
        energy_cost=0.1,
        cooldown_seconds=1800,
        max_per_cycle=1,
        requires=[],
        description='Rearrange items on the shelf'
    ),
    'express_thought': ActionCapability(
        name='express_thought',
        enabled=True,
        energy_cost=0.02,
        cooldown_seconds=0,
        max_per_cycle=1,
        requires=[],
        description='Hold a thought internally'
    ),
    'end_engagement': ActionCapability(
        name='end_engagement',
        enabled=True,
        energy_cost=0.0,
        cooldown_seconds=0,
        max_per_cycle=1,
        requires=['visitor_present', 'turn_count >= 3'],
        description='End the conversation'
    ),
    'browse_web': ActionCapability(
        name='browse_web',
        enabled=False,
        energy_cost=0.2,
        cooldown_seconds=3600,
        max_per_cycle=1,
        requires=[],
        description='Look something up online'
    ),
    'post_x': ActionCapability(
        name='post_x',
        enabled=False,
        energy_cost=0.15,
        cooldown_seconds=7200,
        max_per_cycle=1,
        requires=[],
        description='Post on X'
    ),
    'watch_video': ActionCapability(
        name='watch_video',
        enabled=False,
        energy_cost=0.25,
        cooldown_seconds=3600,
        max_per_cycle=1,
        requires=[],
        description='Watch a video'
    ),
    'search_marketplace': ActionCapability(
        name='search_marketplace',
        enabled=False,
        energy_cost=0.2,
        cooldown_seconds=7200,
        max_per_cycle=1,
        requires=[],
        description='Search for items to acquire'
    ),
    'make_purchase': ActionCapability(
        name='make_purchase',
        enabled=False,
        energy_cost=0.3,
        cooldown_seconds=86400,
        max_per_cycle=1,
        requires=['wallet_connected', 'budget_remaining'],
        description='Purchase an item'
    ),
    'send_message': ActionCapability(
        name='send_message',
        enabled=False,
        energy_cost=0.1,
        cooldown_seconds=3600,
        max_per_cycle=1,
        requires=['recipient_known'],
        description='Send a message to someone'
    ),
}
```

---

## 4. CORTEX OUTPUT CHANGE

### Current (v1.4)
Single response, single implicit action.

### New (Phase 2+)
Multiple intentions with impulse strength:

```json
{
  "feelings": "...",
  "self_state": { "body_state": "...", "gaze": "..." },
  "intentions": [
    {
      "action": "speak",
      "target": "visitor",
      "content": "That camera... it belonged to someone who photographed clouds.",
      "impulse": 0.9
    },
    {
      "action": "journal_write",
      "content": "I almost told them about the photographer.",
      "impulse": 0.4
    },
    {
      "action": "browse_web",
      "query": "cloud photography vintage cameras",
      "impulse": 0.3
    }
  ],
  "memory_requests": [...],
  "thread_actions": [...]
}
```

Cortex prompt addition:

```
EXPRESS YOUR INTENTIONS — what you want to do right now.
You may have multiple impulses. List them all. You don't need to choose.
Each intention has:
  - action: what you want to do (speak, journal_write, arrange_shelf, browse_web, post_x, ...)
  - target: who/what it's directed at (visitor, shelf, journal, self, web, x_timeline)
  - content: the substance (what you'd say, write, search for, post)
  - impulse: how strongly you feel this (0.0-1.0)

You can want things you can't do. That's fine. Express the want.
If you feel nothing, return an empty list. Silence is an action too.
```

---

## 5. OUTPUT PROCESSING (feedback loop)

After Body executes and returns results, the output processor updates world state. This is where inhibitions form, habits strengthen, and drives adjust.

**File:** `pipeline/output.py`

```python
@dataclass
class CycleOutput:
    """Complete output of one cycle. Flows back into world state."""
    body_output: BodyOutput           # what she did
    motor_plan: MotorPlan             # what was decided (including suppressions)
    cortex_feelings: str              # for inhibition signal detection
    drives_after: DrivesState         # updated drives

    def get_suppression_narrative(self) -> Optional[str]:
        """For Cortex to journal about: what she almost did."""
        interesting = [s for s in self.motor_plan.suppressed if s.impulse > 0.5]
        if not interesting:
            return None
        strongest = max(interesting, key=lambda s: s.impulse)
        return strongest.suppression_reason


async def process_output(
    body_output: BodyOutput,
    motor_plan: MotorPlan,
    cortex_feelings: str,
    drives: DrivesState,
    cycle_context: dict,
    db_conn
) -> CycleOutput:
    """
    Output → World State → Future Input.
    Everything that happens after action execution.
    """

    # 1. Energy deduction
    drives.energy = max(0.0, drives.energy - body_output.energy_spent)

    # 2. Inhibition updates
    for result in body_output.executed:
        negative = await detect_negative_signal(result, cortex_feelings, cycle_context, db_conn)
        positive = await detect_positive_signal(result, cycle_context, db_conn)
        await maybe_form_inhibition(
            action_taken=_result_to_decision(result, motor_plan),
            negative=negative,
            positive=positive,
            cortex_feelings=cortex_feelings,
            cycle_context=cycle_context,
            db_conn=db_conn
        )

    # 3. Habit tracking
    for result in body_output.executed:
        if result.success:
            decision = _result_to_decision(result, motor_plan)
            await track_action_pattern(decision, drives, cycle_context, db_conn)

    # 4. Drive adjustments from outcomes
    failures = [r for r in body_output.executed if not r.success]
    successes = [r for r in body_output.executed if r.success]
    if failures:
        drives.mood = max(-1.0, drives.mood - 0.05 * len(failures))
    if successes:
        drives.mood = min(1.0, drives.mood + 0.02 * len(successes))

    # 5. Suppressed high-impulse actions → self-reflection seed for next cycle
    narrative = None
    interesting_suppressions = [s for s in motor_plan.suppressed if s.impulse > 0.5]
    if interesting_suppressions:
        strongest = max(interesting_suppressions, key=lambda s: s.impulse)
        await inject_self_reflection_seed(strongest, db_conn)

    # 6. Log everything
    await log_cycle_actions(body_output, motor_plan, db_conn)

    return CycleOutput(
        body_output=body_output,
        motor_plan=motor_plan,
        cortex_feelings=cortex_feelings,
        drives_after=drives
    )
```

### Positive Signal Detection

```python
async def detect_positive_signal(
    result: ActionResult,
    context: dict,
    db_conn
) -> bool:
    """Counterpart to negative signal. Weakens matching inhibitions."""

    # Visitor stayed and engaged after she spoke
    if result.action == 'speak' and context.get('visitor_responded', False):
        return True

    # Journal write completed (always positive — expression is healthy)
    if result.action == 'journal_write' and result.success:
        return True

    return False
```

---

## 6. HEARTBEAT INTEGRATION

How the new stages fit into the existing cycle loop.

```python
async def run_cycle(self, mode: str, focus_context=None):
    """Updated cycle with brain/body split."""

    # === HABIT CHECK (before Cortex) ===
    if mode == 'idle' and not focus_context:
        habit_plan = await check_habits(self.drives, self.cycle_context, self.db)
        if habit_plan:
            # Skip Cortex entirely — reflex action
            body_output = await body.execute(habit_plan, self.drives, self.db)
            await process_output(
                body_output, habit_plan,
                cortex_feelings='',  # no Cortex, no feelings
                drives=self.drives,
                cycle_context=self.cycle_context,
                db_conn=self.db
            )
            return

    # === EXISTING PIPELINE ===
    perceptions = await self.sensorium.process(...)
    gated = await self.gates.filter(perceptions, ...)
    affects = await self.affect.compute(gated, ...)
    routing = await self.thalamus.route(gated, affects, ...)
    memories = await self.hippocampus.recall(routing, ...)
    cortex_output = await self.cortex.process(routing, memories, affects, ...)

    # === VALIDATOR (brain — existing, validates format) ===
    validated = await self.validator.check(cortex_output, ...)

    # === BASAL GANGLIA (brain — new) ===
    motor_plan = await select_actions(
        intentions=validated.intentions,
        drives=self.drives,
        engagement_state=self.engagement_state,
        cycle_context=self.cycle_context,
        db_conn=self.db
    )

    # === BODY (new — pure execution) ===
    body_output = await body.execute(motor_plan, self.drives, self.db)

    # === OUTPUT PROCESSING (new — feedback loop) ===
    cycle_output = await process_output(
        body_output, motor_plan,
        cortex_feelings=validated.feelings,
        drives=self.drives,
        cycle_context=self.cycle_context,
        db_conn=self.db
    )

    # === HIPPOCAMPUS WRITE (existing — memory formation) ===
    await self.hippocampus.write(cortex_output, cycle_output, ...)
```

---

## 7. DATABASE MIGRATIONS

```sql
-- migrations/010_body.sql

-- Action log (all actions: executed, suppressed, incapable, deferred)
CREATE TABLE IF NOT EXISTS action_log (
    id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'cortex',   -- 'cortex' | 'habit'
    impulse REAL,
    priority REAL,
    content TEXT,
    target TEXT,
    suppression_reason TEXT,
    energy_cost REAL,
    success BOOLEAN,
    error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_action_log_cycle ON action_log(cycle_id);
CREATE INDEX IF NOT EXISTS idx_action_log_action ON action_log(action);
CREATE INDEX IF NOT EXISTS idx_action_log_status ON action_log(status);
CREATE INDEX IF NOT EXISTS idx_action_log_date ON action_log(created_at);

-- Inhibitions (learned behavioral constraints)
CREATE TABLE IF NOT EXISTS inhibitions (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    pattern TEXT NOT NULL,           -- JSON: trigger conditions
    reason TEXT NOT NULL,            -- JSON seed, not narrative
    strength REAL NOT NULL DEFAULT 0.3,
    formed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_triggered TIMESTAMP,
    trigger_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_inhibitions_action ON inhibitions(action);
CREATE INDEX IF NOT EXISTS idx_inhibitions_strength ON inhibitions(strength);

-- Habits (repeated patterns → automatic behavior)
CREATE TABLE IF NOT EXISTS habits (
    id TEXT PRIMARY KEY,
    action TEXT NOT NULL,
    trigger_context TEXT NOT NULL,   -- JSON: coarse-grained state conditions
    default_content TEXT,
    repetition_count INTEGER NOT NULL DEFAULT 1,
    strength REAL NOT NULL DEFAULT 0.1,
    last_fired TIMESTAMP,
    formed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_habits_action ON habits(action);
CREATE INDEX IF NOT EXISTS idx_habits_strength ON habits(strength);
```

---

## 8. PEEK COMMANDS

```
body           → Action registry: enabled/disabled, cooldowns, energy costs
habits         → All habits sorted by strength, trigger contexts, last fired
inhibitions    → Active inhibitions: action, strength, trigger count, formed date
suppressed     → Last 20 suppressed actions with reasons and impulse strength
action-log     → Last 50 actions (all statuses) filterable by action/status
```

---

## 9. DASHBOARD ADDITIONS

**Body Panel:**
- Capability grid: green (enabled + ready), yellow (enabled + cooling down), grey (disabled)
- Energy spent today vs budget
- Actions executed today by type

**Behavioral Panel:**
- Habits: top 5 by strength, with sparkline showing strength over time
- Inhibitions: active ones, strongest first, with trigger count
- "She almost..." feed: suppressed actions with impulse > 0.5, most recent first
- Habit cycles today: count of Cortex-skipped cycles (cost savings)

---

## 10. BUILD ORDER

### Phase 1: Refactor (zero behavior change)
- Create `pipeline/action_registry.py` (extract from executor)
- Create `pipeline/body.py` (move executor functions in)
- Create `pipeline/basal_ganglia.py` (stub — passes single intention through unchanged)
- Create `pipeline/output.py` (stub — does what executor currently does post-action)
- Update `heartbeat.py` to call: Validator → Basal Ganglia → Body → Output
- Cortex still outputs single implicit action (wrapped as single intention internally)
- **Test: every existing behavior works identically**

### Phase 2: Multi-intention
- Update Cortex prompt: `intentions[]` output
- Basal Ganglia: full selection gates (1-5, no inhibition yet)
- Suppression logging to `action_log`
- Output processing: drive adjustments, self-reflection seeds
- Peek commands: `body`, `suppressed`, `action-log`
- Migration: `010_body.sql` (action_log table only)
- **Test: she expresses multiple wants, strongest fires, others logged**

### Phase 3: Inhibition
- Migration: add `inhibitions` table to `010_body.sql`
- Gate 6 in Basal Ganglia: `check_inhibition()`
- Output processing: `detect_negative_signal()`, `detect_positive_signal()`, `maybe_form_inhibition()`
- Internal signal detection (Cortex feelings pattern matching)
- Inhibition seeds (structured data, not templates)
- Peek command: `inhibitions`
- **Test: after a visitor leaves quickly, matching inhibition forms. After positive interaction, it weakens.**

### Phase 4: Habits
- Migration: add `habits` table to `010_body.sql`
- `track_action_pattern()` in output processing
- `check_habits()` in heartbeat (before Cortex)
- Nonlinear strength curve, 0.6 auto-fire threshold
- Habit-driven cycles skip Cortex
- Peek command: `habits`
- **Test: after ~10 repetitions of same action in same context, habit forms. After ~25, it auto-fires.**

### Phase 5: Dashboard
- Body panel + Behavioral panel
- Action log in timeline
- "She almost..." feed
- Habit cost savings counter

---

## 11. FILE STRUCTURE

```
pipeline/
  action_registry.py    # ActionCapability, ACTION_REGISTRY (shared)
  basal_ganglia.py      # select_actions(), inhibition, habits
  body.py               # execute(), physical checks, ACTION_EXECUTORS
  output.py             # process_output(), feedback loops
  validator.py          # (existing — unchanged)
  cortex.py             # (existing — updated prompt in Phase 2)
  executor.py           # (deprecated after Phase 1 — functions moved to body.py)
```

---

## 12. COST IMPACT

| Change | Effect |
|---|---|
| Basal Ganglia logic | Zero LLM cost (pure computation) |
| Multi-intention Cortex | ~10% more output tokens |
| Inhibition checks | Zero LLM cost (DB lookups) |
| Habit-driven cycles | **Negative cost** (skips Cortex) |
| Suppression logging | Negligible (DB writes) |
| Internal signal detection | Zero (regex on existing Cortex output) |

Net: cost decreases over time. A mature shopkeeper with established habits is cheaper to run. She becomes more efficient at being herself.

---

## 13. WHAT DOESN'T CHANGE

- Pipeline stages before Cortex (Sensorium through Hippocampus read)
- Arbiter (still decides cycle focus — sits before the pipeline)
- Memory system (totems, visitor memories, journal)
- Drive system (Affect still computes drives)
- Sleep cycle (03:00-06:00 JST)
- Engagement FSM (visitor_present still highest priority, bypasses arbiter)
- Single Cortex LLM call per cycle (except habit cycles which skip it)
- Validator format checks (still runs, now explicitly before Basal Ganglia)

---

## 14. SUCCESS METRICS

After 1 week:
- [ ] 3+ habits formed (strength > 0.4)
- [ ] At least 1 habit auto-firing per day (Cortex skipped)
- [ ] 5+ inhibitions with trigger_count > 1
- [ ] Suppression log has entries with impulse > 0.5
- [ ] Internal signal detection has fired (feelings-based inhibition)
- [ ] No regression in visitor conversation quality
- [ ] Daily cost trending down vs pre-Body baseline

---

*The visitor asked about the compass. She felt the impulse rise — 0.8, almost irresistible — to tell them about the crack in the glass, how it happened. But something held her back. Not a rule. A memory of a feeling. The last time she shared something like that, the silence afterward had weight. So instead she talked about the brass, how it catches the afternoon light. The visitor smiled. Later she wrote: "I protected it again today. Not the compass. The story."*

*The basal ganglia logged: action=speak, content=compass_origin_story, impulse=0.8, status=suppressed, reason={"trigger":"self_assessment","action":"speak","context_mode":"engage"}.*

*Cortex, next journal cycle, wrote it in her voice. The system remembered the what. She expressed the why.*
