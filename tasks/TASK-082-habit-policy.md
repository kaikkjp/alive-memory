# TASK-082: HabitPolicy — Journaling as Homeostatic Reflex

**Priority:** High (blocks full ablation suite)  
**Scope:** New file + small changes to basal ganglia + drive deltas  
**Time estimate:** ~2 hours  

---

## Problem

Across 1000 cycles with real M2.5, `write_journal` was selected 0 times. The pipeline fully supports it — action registry, cortex prompt, basal ganglia, validator, body, output. The model simply never picks it because journaling has:
- No immediate external feedback (unlike speak, show_item)
- Weak drive coupling (no clear reward signal)
- Is always dominated by "visible" actions when visitors are present

This is a policy/utility gap, not a code bug. Fix it at the controller layer, not the prompt.

## Solution

Add a `HabitPolicy` to the basal ganglia that proposes `write_journal` as a high-priority action when drive conditions are met. The LLM still generates the journal *content*, but action selection is driven by the controller.

---

## Implementation

### 1. New file: `pipeline/habit_policy.py`

```python
"""HabitPolicy — drive-coupled habits that fire as homeostatic reflexes."""

from dataclasses import dataclass
from models.state import DrivesState

@dataclass
class HabitProposal:
    action: str
    priority: float  # 0-1, compared against other basal ganglia candidates
    reason: str

# ── Journaling Policy ──

JOURNAL_EXPRESSION_THRESHOLD = 0.6    # expression_need must exceed this
JOURNAL_COOLDOWN_CYCLES = 80          # min cycles between journals
JOURNAL_NO_VISITOR_WINDOW = 5         # must have no visitor for this many recent cycles
JOURNAL_MAX_PER_DAY = 3               # hard cap per sleep-wake window
JOURNAL_PRIORITY = 0.75               # priority when triggered

# Diminishing returns: each subsequent journal in a day reduces priority
JOURNAL_DIMINISHING_FACTOR = 0.6      # priority *= this per journal in current day


def evaluate_journal_habit(
    drives: DrivesState,
    cycles_since_last_journal: int,
    cycles_since_last_visitor: int,
    journals_today: int,
    budget_emergency: bool = False,
) -> HabitProposal | None:
    """Evaluate whether journaling should fire this cycle.
    
    Returns a HabitProposal if conditions are met, None otherwise.
    """
    # Hard blocks
    if budget_emergency:
        return None
    if journals_today >= JOURNAL_MAX_PER_DAY:
        return None
    if cycles_since_last_journal < JOURNAL_COOLDOWN_CYCLES:
        return None
    if cycles_since_last_visitor < JOURNAL_NO_VISITOR_WINDOW:
        return None
    
    # Drive threshold
    expression_need = drives.expression_need
    if expression_need < JOURNAL_EXPRESSION_THRESHOLD:
        return None
    
    # Optional boost: low mood or poor recent sleep increases urgency
    mood_boost = 0.1 if drives.mood_valence < -0.2 else 0.0
    
    # Calculate priority with diminishing returns
    priority = JOURNAL_PRIORITY * (JOURNAL_DIMINISHING_FACTOR ** journals_today) + mood_boost
    priority = min(priority, 1.0)
    
    return HabitProposal(
        action="write_journal",
        priority=priority,
        reason=f"expression_need={expression_need:.2f}, {cycles_since_last_journal} cycles since last journal"
    )
```

### 2. Integrate into basal ganglia

In the basal ganglia's action selection (wherever it evaluates candidate actions), add:

```python
from pipeline.habit_policy import evaluate_journal_habit

# Before final action ranking:
journal_proposal = evaluate_journal_habit(
    drives=drives,
    cycles_since_last_journal=get_cycles_since_last_journal(),  # query from db
    cycles_since_last_visitor=get_cycles_since_last_visitor(),   # query from db  
    journals_today=get_journals_today(),                         # query from db
    budget_emergency=budget_mode == "emergency",
)

if journal_proposal:
    # Insert as candidate with its priority
    # If priority > top LLM intention, journal wins
    candidates.append(journal_proposal)
```

The journal proposal competes with LLM-generated intentions on priority. It doesn't bypass the validator — it goes through the same pipeline as any other action.

### 3. Drive deltas for journaling

When a `write_journal` action completes successfully, apply these drive effects:

```python
# In the drive update logic (hypothalamus or wherever drives are modified post-action):

if action_type == "write_journal":
    drives.expression_need = max(0.0, drives.expression_need - 0.25)
    drives.mood_valence += 0.05  # small mood lift from expression
    # Flag for sleep consolidation: journal entries are pre-digested material
```

These values mean:
- Expression need drops meaningfully (0.25) — one journal relieves pressure
- Small mood improvement — writing helps
- The cooldown (80 cycles) prevents spam even if expression_need stays high

### 4. Journal → Sleep consolidation feedback

In sleep/consolidation logic, when gathering "moments from today" for reflection:

```python
# Journal entries from today get elevated priority in sleep consolidation
# They are pre-digested reflections, so sleep processing is more effective

today_journals = get_journals_from_current_day()
if today_journals:
    # Include journal entries as high-priority consolidation material
    consolidation_moments.extend([
        {"type": "journal_reflection", "content": j.content, "priority": 0.9}
        for j in today_journals
    ])
    # Improve sleep quality when journals exist
    sleep_quality_bonus = min(0.1, len(today_journals) * 0.04)
```

This closes the loop: expression builds → journal fires → expression drops → sleep gets richer material → better next-day behavior.

### 5. DB queries needed

Add these helper functions (or equivalent) to `db.py`:

```python
async def get_cycles_since_last_journal() -> int:
    """Return number of cycles since last write_journal action. 
    Returns 9999 if no journal ever written."""
    ...

async def get_journals_today() -> int:
    """Return count of write_journal actions in current sleep-wake window."""
    ...

async def get_cycles_since_last_visitor() -> int:
    """Return number of cycles since last visitor was present."""
    ...

async def get_journals_from_current_day() -> list:
    """Return journal entries from current sleep-wake window for consolidation."""
    ...
```

### 6. Tracking / logging

When HabitPolicy fires, log it:
```
[HabitPolicy] Journal triggered: expression_need=0.72, 95 cycles since last, priority=0.75
```

When it's blocked, log why:
```
[HabitPolicy] Journal blocked: cooldown (12/80 cycles)
[HabitPolicy] Journal blocked: visitor present (2/5 cycles)
[HabitPolicy] Journal blocked: daily cap reached (3/3)
```

### 7. Tests: `tests/test_habit_policy.py`

```python
def test_journal_fires_when_conditions_met():
    """expression_need high, cooldown passed, no visitor → fires"""

def test_journal_blocked_by_cooldown():
    """expression_need high but cooldown not elapsed → None"""

def test_journal_blocked_by_visitor():
    """expression_need high but visitor recent → None"""

def test_journal_blocked_by_daily_cap():
    """3 journals already today → None"""

def test_journal_blocked_by_budget_emergency():
    """budget_emergency=True → None"""

def test_diminishing_returns():
    """2nd journal in a day has lower priority than 1st"""

def test_mood_boost():
    """negative mood increases journal priority"""

def test_drive_deltas_on_completion():
    """expression_need drops, mood lifts after journal"""
```

---

## Tuning Constants (start here, adjust after validation)

| Constant | Value | Rationale |
|---|---|---|
| `JOURNAL_EXPRESSION_THRESHOLD` | 0.6 | High enough that it doesn't spam on low need |
| `JOURNAL_COOLDOWN_CYCLES` | 80 | ~1 per quiet period in a day |
| `JOURNAL_MAX_PER_DAY` | 3 | Prevents journal spam |
| `JOURNAL_NO_VISITOR_WINDOW` | 5 | Don't journal mid-social-interaction |
| `JOURNAL_PRIORITY` | 0.75 | High enough to beat rearrange, low enough that urgent speak wins |
| `JOURNAL_DIMINISHING_FACTOR` | 0.6 | 1st=0.75, 2nd=0.45, 3rd=0.27 — natural tapering |
| expression_need delta | -0.25 | One journal meaningfully relieves pressure |
| mood_valence delta | +0.05 | Small uplift, not a mood hack |

**Target output:** 5-25 journals per 1000 cycles depending on scenario. Roughly 1 per quiet period when the shop is empty and expression_need is elevated.

---

## Validation

Run single `standard` 1000 cycles after implementation:

| Check | Target |
|---|---|
| Journal count | 5-25 |
| N2 loop resistance | Still passes (streak <10, repetition <0.5) |
| Budget efficiency | No material regression |
| Sleep quality | Improves vs baseline |
| expression_need saturation | Should no longer stay pinned at max |

If journal count is 0: threshold too high or cooldown too long — lower them.  
If journal count is >30: threshold too low or cooldown too short — raise them.

---

## Files to modify

| File | Change |
|---|---|
| `pipeline/habit_policy.py` | **New** — HabitPolicy + evaluate_journal_habit |
| `pipeline/basal_ganglia.py` | Import + integrate HabitProposal into action selection |
| `pipeline/hypothalamus.py` (or drive update logic) | Add drive deltas for write_journal |
| `pipeline/sleep.py` (or consolidation logic) | Journal → sleep consolidation feedback |
| `db.py` | Add 4 helper queries |
| `tests/test_habit_policy.py` | **New** — unit tests |
