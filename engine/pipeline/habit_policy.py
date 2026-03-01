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
from alive_config import cfg


@dataclass
class HabitProposal:
    action: str
    priority: float  # 0-1, compared against other basal ganglia candidates
    reason: str


# ── Journaling Policy — all thresholds from alive_config.yaml ──

JOURNAL_EXPRESSION_THRESHOLD = cfg('habit_policy.journal.expression_threshold', 0.6)
JOURNAL_COOLDOWN_CYCLES = cfg('habit_policy.journal.cooldown_cycles', 80)
JOURNAL_NO_VISITOR_WINDOW = cfg('habit_policy.journal.no_visitor_window', 5)
JOURNAL_PRIORITY = cfg('habit_policy.journal.priority', 0.75)


def evaluate_journal_habit(
    drives: DrivesState,
    cycles_since_last_journal: int,
    cycles_since_last_visitor: int,
    budget_emergency: bool = False,
) -> HabitProposal | None:
    """Evaluate whether journaling should fire this cycle.

    TASK-105: Daily cap removed. Drives are the sole rate limiter.
    Expression_need drops ~0.12 per journal, so after ~5 journals it's
    near zero and this policy stops firing. Budget is the ultimate cap.

    Returns a HabitProposal if conditions are met, None otherwise.
    """
    # Hard blocks
    if budget_emergency:
        print("[HabitPolicy] Journal blocked: budget emergency")
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
    mood_boost = cfg('habit_policy.journal.mood_boost_amount', 0.1) if drives.mood_valence < cfg('habit_policy.journal.mood_boost_threshold', -0.2) else 0.0

    priority = min(JOURNAL_PRIORITY + mood_boost, 1.0)

    reason = f"expression_need={expression_need:.2f}, {cycles_since_last_journal} cycles since last journal"
    print(f"[HabitPolicy] Journal triggered: {reason}, priority={priority:.2f}")

    return HabitProposal(
        action="write_journal",
        priority=priority,
        reason=reason,
    )
