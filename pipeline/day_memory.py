"""Day Memory — ephemeral moment extraction. No LLM. Deterministic."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import clock
import db


MOMENT_THRESHOLD = 0.4
MAX_DAY_MEMORIES = 30


@dataclass
class DayMemoryEntry:
    id: str
    ts: datetime
    salience: float
    moment_type: str
    visitor_id: Optional[str]
    summary: str
    raw_refs: dict = field(default_factory=dict)
    tags: list = field(default_factory=list)
    # DB-populated fields (not set during construction in maybe_record_moment)
    retry_count: int = 0
    processed_at: Optional[datetime] = None


async def maybe_record_moment(cycle_result: dict, cycle_context: dict) -> None:
    """Check if this cycle produced a salient moment. No LLM.

    Called at the end of every cognitive cycle in heartbeat.run_cycle().
    """
    salience = compute_moment_salience(cycle_result, cycle_context)

    if salience < MOMENT_THRESHOLD:
        return  # not worth remembering today

    moment = DayMemoryEntry(
        id=str(uuid.uuid4()),
        ts=clock.now_utc(),
        salience=salience,
        moment_type=classify_moment(cycle_result, cycle_context),
        visitor_id=cycle_context.get('visitor_id'),
        summary=build_moment_summary(cycle_result, cycle_context),
        raw_refs={
            'cycle_id': cycle_context['cycle_id'],
            'event_ids': cycle_context.get('event_ids', []),
        },
        tags=extract_moment_tags(cycle_result, cycle_context),
    )

    await db.insert_day_memory(moment)


def compute_moment_salience(result: dict, ctx: dict) -> float:
    """Deterministic salience scoring for day memory moments.

    Resonance Formula (TASK-025):
    ─────────────────────────────
    Salience is computed at creation time from cycle signals. Each factor
    contributes a continuous or boolean bonus to a 0.0–1.0 score:

    BOOLEAN SIGNALS (rare, high-value events):
      +0.40  internal_conflict — she noticed self-inconsistency
      +0.30  had_contradiction — shift_candidate from previous cycle
      +0.25  gift interaction  — accept_gift or decline_gift action
      +0.10  dropped actions   — validator blocked something she wanted

    CORTEX RESONANCE FLAG (common, scaled down to avoid flat scores):
      +0.20  resonance: true from cortex (emotional resonance)

    CONTINUOUS SIGNALS (produce per-moment variance):
      0.00–0.25  drive delta  — max abs change across all drives, scaled
                                linearly: delta * 0.83, capped at 0.25
      0.00–0.15  trust bonus  — stranger=0, returner=0.05, regular=0.10,
                                familiar=0.15
      0.00–0.12  content richness — monologue word count / 500, capped 0.08
                                  + dialogue word count / 400, capped 0.04
                                  (longer/richer cycle output = higher salience)
      0.00–0.10  action diversity — 0.05 per distinct action type, capped 0.10
      +0.08      self-expression — write_journal or post_x_draft action
      0.00–0.05  mode bonus   — engage=0.05, express=0.03, consume=0.02

    Final score clamped to [0.0, 1.0].

    These continuous factors ensure that even cycles with the same boolean
    signals (e.g., resonance=True + journal_write) produce different salience
    values based on emotional intensity, content depth, and action variety.
    """
    score = 0.0

    # ── Boolean signals: rare, high-value events ──

    # Internal conflict always worth remembering (Phase 3)
    if ctx.get('has_internal_conflict'):
        score += 0.4

    # Cortex resonance flag — scaled down from 0.4 to 0.2 because cortex
    # sets this frequently; the old 0.4 dominated and flattened all scores
    if result.get('resonance'):
        score += 0.2

    # Contradictions are always interesting
    if ctx.get('had_contradiction'):
        score += 0.3

    # Gifts carry weight
    if any(a.get('type') in ('accept_gift', 'decline_gift')
           for a in result.get('actions', [])):
        score += 0.25

    # Validator dropped something (she wanted to but couldn't)
    if result.get('_dropped_actions'):
        score += 0.1

    # ── Continuous signals: produce per-moment variance ──

    # Emotional intensity: scale drive delta linearly (not threshold)
    drive_delta = ctx.get('max_drive_delta', 0.0)
    score += min(0.25, drive_delta * 0.83)

    # Visitor trust level amplifies everything
    trust_bonus = {
        'stranger': 0.0, 'returner': 0.05,
        'regular': 0.10, 'familiar': 0.15,
    }
    score += trust_bonus.get(ctx.get('trust_level', 'stranger'), 0.0)

    # Content richness: longer monologue/dialogue = more salient
    monologue = result.get('internal_monologue') or ''
    dialogue = result.get('dialogue') or ''
    monologue_words = len(monologue.split()) if monologue.strip() else 0
    dialogue_words = len(dialogue.split()) if dialogue.strip() else 0
    score += min(0.08, monologue_words / 500)
    score += min(0.04, dialogue_words / 400)

    # Action diversity: more distinct actions = richer cycle
    action_types = set()
    for a in result.get('actions', []):
        a_type = a.get('type', '')
        if a_type:
            action_types.add(a_type)
    score += min(0.10, len(action_types) * 0.05)

    # Self-expression (journal, post) — reduced from 0.15 to 0.08
    # since action_diversity already gives credit for having actions
    if any(a.get('type') in ('write_journal', 'post_x_draft')
           for a in result.get('actions', [])):
        score += 0.08

    # Mode-based base: some cycle types are inherently more interesting
    mode = ctx.get('mode', '')
    mode_bonus = {
        'engage': 0.05, 'express': 0.03, 'consume': 0.02,
    }
    score += mode_bonus.get(mode, 0.0)

    return min(1.0, score)


def classify_moment(result: dict, ctx: dict) -> str:
    """Classify the moment type. Returns highest-priority match."""
    # Internal conflict is highest priority (Phase 3)
    if ctx.get('has_internal_conflict'):
        return 'internal_conflict'

    if result.get('resonance'):
        return 'resonance'

    if ctx.get('had_contradiction'):
        return 'contradiction'

    if any(a.get('type') in ('accept_gift', 'decline_gift')
           for a in result.get('actions', [])):
        return 'gift'

    if ctx.get('max_drive_delta', 0.0) > 0.3:
        return 'emotional_peak'

    if ctx.get('is_abrupt_end'):
        return 'abrupt_end'

    if any(a.get('type') in ('write_journal', 'post_x_draft')
           for a in result.get('actions', [])):
        return 'self_expression'

    if ctx.get('is_novel_topic'):
        return 'novel_topic'

    if ctx.get('is_silence_moment'):
        return 'silence'

    # Fallback: if it passed salience threshold, call it resonance
    return 'resonance'


def build_moment_summary(result: dict, ctx: dict) -> str:
    """Build a diegetic 1-3 sentence summary. Deterministic. No LLM."""
    parts = []

    # Internal conflict summary (Phase 3)
    if ctx.get('has_internal_conflict'):
        conflict_desc = ctx.get('internal_conflict_description', 'something felt off')
        parts.append(f"I noticed something about myself: {conflict_desc}.")
        return " ".join(parts[:4])

    # Who was there
    visitor_name = ctx.get('visitor_name')
    if visitor_name:
        parts.append(f"{visitor_name} was here.")
    elif ctx.get('visitor_id'):
        parts.append("A visitor was here.")

    # What was said (her side)
    dialogue = result.get('dialogue')
    if dialogue and dialogue != '...':
        parts.append(f'I said: "{dialogue[:100]}"')

    # What she thought
    monologue = result.get('internal_monologue')
    if monologue:
        parts.append(f"I was thinking: {monologue[:80]}")

    # What happened (actions)
    for action in result.get('actions', [])[:2]:
        action_type = action.get('type', '')
        if action_type == 'accept_gift':
            title = action.get('detail', {}).get('title', 'something')
            parts.append(f"I accepted a gift: {title}")
        elif action_type == 'decline_gift':
            parts.append("I declined a gift.")
        elif action_type == 'write_journal':
            parts.append("I wrote in my journal.")

    # What was dropped (frustrated intent)
    for drop in result.get('_dropped_actions', [])[:1]:
        parts.append(
            f"I wanted to {drop.get('action', {}).get('type', '?')} "
            f"but couldn't: {drop.get('reason', '?')}"
        )

    return " ".join(parts[:4])  # cap at 4 parts


def extract_moment_tags(result: dict, ctx: dict) -> list[str]:
    """Extract semantic tags for search/filtering."""
    tags = []

    # Moment type as tag
    moment_type = classify_moment(result, ctx)
    tags.append(moment_type)

    # Visitor name if known
    if ctx.get('visitor_name'):
        tags.append(ctx['visitor_name'].lower())

    # Action types
    for action in result.get('actions', []):
        action_type = action.get('type', '')
        if action_type:
            tags.append(action_type)

    # Key words from dialogue (simple extraction)
    dialogue = result.get('dialogue', '') or ''
    if len(dialogue) > 10 and dialogue != '...':
        words = dialogue.lower().split()
        # Extract words > 5 chars as rough topic tags
        long_words = [w.strip('.,!?;:"\'') for w in words if len(w) > 5]
        tags.extend(long_words[:3])

    return list(dict.fromkeys(tags))  # deduplicate, preserve order
