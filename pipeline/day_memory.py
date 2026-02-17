"""Day Memory — ephemeral moment extraction. No LLM. Deterministic."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import clock
import db


MOMENT_THRESHOLD = 0.35
MAX_DAY_MEMORIES = 30

# Humanized action names for diegetic summaries (no system language in memories)
ACTION_NAMES = {
    'write_journal': 'write in my journal',
    'post_x_draft': 'post something',
    'rearrange': 'rearrange the collection',
    'speak': 'say something',
    'express_thought': 'express a thought',
    'close_shop': 'close the shop',
    'open_shop': 'open the shop',
    'place_item': 'place an item',
    'show_item': 'show something',
    'end_engagement': 'step away',
    'accept_gift': 'accept a gift',
    'decline_gift': 'decline a gift',
}


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
    nap_processed: bool = False


async def maybe_record_moment(cycle_result: dict, cycle_context: dict) -> None:
    """Check if this cycle produced a salient moment. No LLM.

    Called at the end of every cognitive cycle in heartbeat.run_cycle().
    Enriches context with event salience_dynamic from TASK-045 before scoring.
    """
    # Enrich context with TASK-045 salience engine signal (don't mutate caller's dict)
    enriched_ctx = dict(cycle_context)
    event_ids = cycle_context.get('event_ids', [])
    if event_ids:
        try:
            max_sal = await db.get_max_event_salience_dynamic(event_ids)
            enriched_ctx['event_salience_dynamic'] = max_sal
        except Exception:
            pass  # DB lookup failure must not block moment recording

    salience = compute_moment_salience(cycle_result, enriched_ctx)

    if salience < MOMENT_THRESHOLD:
        return  # not worth remembering today

    print(f"  [DayMemory] Recording moment: salience={salience:.3f} "
          f"type={classify_moment(cycle_result, enriched_ctx)} "
          f"mode={enriched_ctx.get('mode')}")

    moment = DayMemoryEntry(
        id=str(uuid.uuid4()),
        ts=clock.now_utc(),
        salience=salience,
        moment_type=classify_moment(cycle_result, enriched_ctx),
        visitor_id=enriched_ctx.get('visitor_id'),
        summary=build_moment_summary(cycle_result, enriched_ctx),
        raw_refs={
            'cycle_id': enriched_ctx['cycle_id'],
            'event_ids': enriched_ctx.get('event_ids', []),
        },
        tags=extract_moment_tags(cycle_result, enriched_ctx),
    )

    await db.insert_day_memory(moment)


def compute_moment_salience(result: dict, ctx: dict) -> float:
    """Deterministic salience scoring for day memory moments.

    TASK-050 Base Salience Model:
    ─────────────────────────────
    Each cycle gets a guaranteed BASE salience from its primary trigger.
    Modulation adds up to ~0.20 on top. This ensures meaningful actions
    always produce moments (base >= threshold), while idle fidgets don't.

    BASE SALIENCE (highest matching trigger wins):
      0.80  internal_conflict — she noticed self-inconsistency
      0.70  visitor interaction — engage mode with visitor events
      0.60  read_content executed — she consumed from the pool
      0.55  thread created or updated
      0.50  write_journal executed (with content)
      0.40  express_thought with monologue content
      0.00  idle fidget only — no moment

    MODULATION (additive, capped):
      0.00–0.10  drive delta — max abs change * 0.33
      0.00–0.10  trust bonus — stranger=0, returner=0.03, regular=0.06, familiar=0.10
      0.00–0.05  content richness — (monologue + dialogue word count) / 1000
      +0.05      resonance flag from cortex
      +0.05      mood extremes — valence < -0.3 or > 0.5
      0.00–0.05  event salience from TASK-045

    Recording threshold: 0.35. Final score clamped to [0.0, 1.0].
    """
    actions = result.get('actions', [])
    action_types = {a.get('type', '') for a in actions}

    # ── Determine base salience from highest-priority trigger ──
    base = 0.0

    # Internal conflict — highest priority
    if ctx.get('has_internal_conflict'):
        base = max(base, 0.80)

    # Contradiction from previous cycle
    if ctx.get('had_contradiction'):
        base = max(base, 0.75)

    # Visitor interaction (engage mode or visitor events present)
    if ctx.get('mode') == 'engage' or ctx.get('visitor_id'):
        base = max(base, 0.70)

    # Gift interaction
    if action_types & {'accept_gift', 'decline_gift'}:
        base = max(base, 0.70)

    # Content consumed (read_content, consume/news mode)
    if 'read_content' in action_types or ctx.get('mode') in ('consume', 'news'):
        base = max(base, 0.60)

    # Thread work
    if action_types & {'thread_update', 'thread_create', 'thread_close'}:
        base = max(base, 0.55)

    # Journal with actual content
    if any(a.get('type') == 'write_journal'
           and a.get('detail', {}).get('text', '').strip()
           for a in actions):
        base = max(base, 0.50)

    # Post draft
    if 'post_x_draft' in action_types:
        base = max(base, 0.50)

    # Express thought with monologue content
    monologue = result.get('internal_monologue') or ''
    if 'express_thought' in action_types and len(monologue.split()) > 5:
        base = max(base, 0.40)

    # Resonance alone (common, lower base — still above threshold)
    if result.get('resonance') and base < 0.36:
        base = max(base, 0.36)

    # Dropped actions (frustrated intent) — worth noting
    if result.get('_dropped_actions') and base < 0.36:
        base = max(base, 0.36)

    # If nothing meaningful happened (idle fidget, no actions, no resonance),
    # base stays 0.0 → below threshold → no moment recorded.
    if base < MOMENT_THRESHOLD:
        return base

    # ── Modulation: small additive variance on top of base ──
    mod = 0.0

    # Drive intensity at time of action
    drive_delta = ctx.get('max_drive_delta', 0.0)
    mod += min(0.10, drive_delta * 0.33)

    # Trust level (novelty of first encounter vs familiar comfort)
    trust_bonus = {
        'stranger': 0.0, 'returner': 0.03,
        'regular': 0.06, 'familiar': 0.10,
    }
    mod += trust_bonus.get(ctx.get('trust_level', 'stranger'), 0.0)

    # Content richness
    dialogue = result.get('dialogue') or ''
    total_words = (len(monologue.split()) if monologue.strip() else 0) + \
                  (len(dialogue.split()) if dialogue.strip() else 0)
    mod += min(0.05, total_words / 1000)

    # Cortex resonance
    if result.get('resonance'):
        mod += 0.05

    # Mood extremes — she's feeling strongly
    # (mood_valence not directly available in result, but drive_delta captures it)

    # Event salience from TASK-045
    event_sal = ctx.get('event_salience_dynamic', 0.0)
    if event_sal > 0:
        mod += min(0.05, event_sal * 0.1)

    return min(1.0, base + mod)


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
        raw_type = drop.get('action', {}).get('type', '?')
        human_name = ACTION_NAMES.get(raw_type, raw_type.replace('_', ' '))
        reason = drop.get('reason', '')
        if 'conversation' in reason:
            parts.append(f"I wanted to {human_name} but I was with someone.")
        else:
            parts.append(f"I wanted to {human_name} but something held me back.")

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
