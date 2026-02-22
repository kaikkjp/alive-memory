"""HabitPolicy — drive-coupled habits that fire as homeostatic reflexes.

Unlike learned habits (which match trigger_context patterns from experience),
habit policies are hard-coded drive thresholds that guarantee certain actions
fire when conditions are met. The LLM still generates content; the policy
only controls action *selection*.

TASK-082: Journaling policy — write_journal fires when expression_need is
elevated, cooldown has elapsed, and no visitor is present.
"""

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
        print("[HabitPolicy] Journal blocked: budget emergency")
        return None
    if journals_today >= JOURNAL_MAX_PER_DAY:
        print(f"[HabitPolicy] Journal blocked: daily cap reached ({journals_today}/{JOURNAL_MAX_PER_DAY})")
        return None
    if cycles_since_last_journal < JOURNAL_COOLDOWN_CYCLES:
        print(f"[HabitPolicy] Journal blocked: cooldown ({cycles_since_last_journal}/{JOURNAL_COOLDOWN_CYCLES} cycles)")
        return None
    if cycles_since_last_visitor < JOURNAL_NO_VISITOR_WINDOW:
        print(f"[HabitPolicy] Journal blocked: visitor present ({cycles_since_last_visitor}/{JOURNAL_NO_VISITOR_WINDOW} cycles)")
        return None

    # Drive threshold
    expression_need = drives.expression_need
    if expression_need < JOURNAL_EXPRESSION_THRESHOLD:
        return None

    # Optional boost: low mood increases urgency
    mood_boost = 0.1 if drives.mood_valence < -0.2 else 0.0

    # Calculate priority with diminishing returns
    priority = JOURNAL_PRIORITY * (JOURNAL_DIMINISHING_FACTOR ** journals_today) + mood_boost
    priority = min(priority, 1.0)

    reason = f"expression_need={expression_need:.2f}, {cycles_since_last_journal} cycles since last journal"
    print(f"[HabitPolicy] Journal triggered: {reason}, priority={priority:.2f}")

    return HabitProposal(
        action="write_journal",
        priority=priority,
        reason=reason,
    )
