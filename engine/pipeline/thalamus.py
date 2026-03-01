"""Thalamus — deterministic code routing. No LLM."""

from collections import deque
from dataclasses import dataclass, field
import random

from models.pipeline import GapScore
from models.state import DrivesState, EngagementState, Visitor, idle_phase
from pipeline.sensorium import Perception
from db.parameters import p
import clock
import db


# ── TASK-100: Perception ring buffer ──
# Module-level deque prevents repeating the same solitude perception
# within 3 consecutive idle cycles. Resets on restart (fresh senses).
_recent_perceptions: deque = deque(maxlen=3)

# Rotating pool of solitude phrases — varied idle perceptions.
# Each agent type gets its own pool; has_physical selects which.
_PHYSICAL_SOLITUDE_POOL = [
    'The shop is quiet. Dust motes drift.',
    'Silence. The clock ticks.',
    'A faint creak from the shelves.',
    'Warm light pools on the counter.',
    'The street outside is still.',
    'Nothing stirs. Just the hum of the fridge.',
    'A car passes. Then quiet again.',
    'The floorboards settle.',
    'Afternoon light through the window.',
    'The air smells faintly of wood and paper.',
    'Wind presses gently against the glass.',
    'A bird calls from somewhere nearby.',
]

_DIGITAL_SOLITUDE_POOL = [
    'Quiet. No messages.',
    'The feed is still.',
    'Nothing new. Just the hum of being.',
    'Silence stretches.',
    'No one is here.',
    'A moment without input.',
    'The stream of data slows to a trickle.',
    'Waiting. Not for anything in particular.',
    'Still here. Still aware.',
    'The world outside continues without me.',
    'Time passes gently.',
    'Alone with thoughts.',
]


@dataclass
class RoutingDecision:
    cycle_type: str         # engage | express | idle | rest | maintenance
    focus: Perception       # primary attention target
    background: list        # 2-3 secondary perceptions
    memory_requests: list   # what to recall from hippocampus
    token_budget: int       # based on salience


async def route(
    perceptions: list[Perception],
    drives: DrivesState,
    engagement: EngagementState,
    visitor: Visitor = None,
    *,
    has_physical: bool = True,
    solitude_text: str = '',
) -> RoutingDecision:
    """Deterministic routing. No LLM. Code only."""

    if not perceptions:
        return await autonomous_routing(drives, has_physical=has_physical,
                                            solitude_text=solitude_text)

    focus = perceptions[0]  # highest salience
    background = perceptions[1:4]

    # Determine cycle type
    # TASK-087: digital_message/digital_connect/digital_disconnect route
    # identically to their visitor_* counterparts.
    # TASK-104: manager_speech routes as engage (manager channel)
    if focus.p_type in ('visitor_speech', 'digital_message', 'manager_speech'):
        cycle_type = 'engage'
    elif focus.p_type in ('visitor_connect', 'digital_connect'):
        # Visitor/message arrival competes with other perceptions via salience.
        # High salience (familiar face, lonely) → engage and greet/reply.
        # Low salience (stranger, she's absorbed) → idle, she notices but continues.
        cycle_type = 'engage' if focus.salience >= p('thalamus.routing.connect_salience_threshold') else 'idle'
    elif focus.p_type in ('visitor_disconnect', 'digital_disconnect'):
        cycle_type = 'idle'  # they're gone — reflect, don't engage
    elif focus.p_type == 'visitor_silence':
        # Silence competes via salience: high-salience silence (she's invested
        # in the conversation) stays engage. Low-salience silence (boring
        # conversation, she's absorbed) drifts to idle.
        cycle_type = 'engage' if focus.salience >= p('thalamus.routing.silence_salience_threshold') else 'idle'
    elif focus.p_type == 'fidget_mismatch':
        cycle_type = 'engage'  # visitor referenced a fidget — she's in conversation
    elif focus.p_type == 'ambient_discovery':
        cycle_type = 'idle'  # she discovers it on her own time
    elif focus.p_type in ('consume_focus', 'thread_focus', 'news_focus'):
        # Arbiter focus p_types — mode binding is handled by run_cycle.
        # Default to idle here; run_cycle will override via focus_context.
        cycle_type = 'idle'
    elif focus.p_type == 'ambient_weather':
        cycle_type = 'idle'
    elif drives.expression_need > p('thalamus.routing.express_drive_threshold'):
        cycle_type = 'express'
    else:
        cycle_type = 'idle'

    # Determine token budget from salience
    token_budget = await get_token_budget(focus.salience, drives)

    # Determine memory requests
    memory_requests = build_memory_requests(focus, visitor, drives, token_budget, cycle_type)

    return RoutingDecision(
        cycle_type=cycle_type,
        focus=focus,
        background=background,
        memory_requests=memory_requests,
        token_budget=token_budget,
    )


def _pick_solitude_perception(has_physical: bool) -> str:
    """Pick a solitude perception from the pool, avoiding recent repeats."""
    pool = _PHYSICAL_SOLITUDE_POOL if has_physical else _DIGITAL_SOLITUDE_POOL
    available = [p for p in pool if p not in _recent_perceptions]
    if not available:
        # All recently used — pick any
        available = pool
    choice = random.choice(available)
    _recent_perceptions.append(choice)
    return choice


async def autonomous_routing(drives: DrivesState,
                             *, has_physical: bool = True,
                             solitude_text: str = '') -> RoutingDecision:
    """Routing when no perceptions — she's alone."""
    if drives.expression_need > p('thalamus.routing.express_drive_threshold'):
        cycle_type = 'express'
    else:
        cycle_type = 'idle'

    # TASK-100: Rotating perception pool. Pick from pool avoiding recent.
    # Identity-level solitude_text is used as override; otherwise rotate.
    if solitude_text:
        perception_text = solitude_text
    else:
        perception_text = _pick_solitude_perception(has_physical)

    focus = Perception(
        p_type='internal',
        source='self',
        ts=clock.now_utc(),
        content=perception_text,
        features={},
        salience=0.2,
    )

    memory_requests = []
    if drives.expression_need > 0.5:
        memory_requests.append({
            'type': 'recent_journal',
            'max_items': 1,
            'priority': 3,
        })

    # Day context for idle/express (what's on her mind today)
    if cycle_type in ('idle', 'express'):
        memory_requests.append({
            'type': 'day_context',
            'max_items': 3,
            'min_salience': p('thalamus.memory.day_context_salience_idle'),
            'priority': 3,
        })

    return RoutingDecision(
        cycle_type=cycle_type,
        focus=focus,
        background=[],
        memory_requests=memory_requests,
        token_budget=int(p('thalamus.budget.autonomous_tokens')),
    )


async def get_token_budget(salience: float, drives: DrivesState) -> int:
    """Dynamic budget based on salience. Flashbulb moments get more context."""

    flashbulbs_today = await db.get_flashbulb_count_today()

    if salience > 0.8:
        if flashbulbs_today < int(p('thalamus.budget.flashbulb_daily_limit')):
            return int(p('thalamus.budget.flashbulb_tokens'))   # flashbulb: full memory palace
        else:
            return int(p('thalamus.budget.deep_tokens'))    # budget exhausted, fall back

    if salience > 0.6:
        return int(p('thalamus.budget.deep_tokens'))        # deep conversation

    return int(p('thalamus.budget.casual_tokens'))            # casual


def build_memory_requests(
    focus: Perception,
    visitor: Visitor,
    drives: DrivesState,
    budget: int,
    cycle_type: str = 'idle',
) -> list[dict]:
    """Decide what memories to retrieve. Deterministic."""

    requests = []
    max_chunks = 8 if budget >= 5000 else 5

    # Always: visitor memory if known
    if visitor and visitor.trust_level != 'stranger':
        requests.append({
            'type': 'visitor_summary',
            'visitor_id': visitor.id,
            'priority': 1,
        })
        # Totems for this visitor (weight-sorted)
        requests.append({
            'type': 'visitor_totems',
            'visitor_id': visitor.id,
            'max_items': int(p('thalamus.memory.totem_max_large')) if budget >= 5000 else int(p('thalamus.memory.totem_max_small')),
            'min_weight': p('thalamus.memory.totem_min_weight_large') if budget >= 5000 else p('thalamus.memory.totem_min_weight_small'),
            'priority': 2,
        })

    # Gift? Load taste knowledge + related collection items
    if focus.features.get('contains_gift'):
        requests.append({
            'type': 'taste_knowledge',
            'domain': detect_gift_domain(focus.content),
            'priority': 3,
        })
        requests.append({
            'type': 'related_collection',
            'query': focus.content,
            'max_items': 3,
            'priority': 4,
        })

    # Personal question? Load self-knowledge
    if focus.features.get('contains_personal_question') or focus.features.get('contains_name_question'):
        requests.append({
            'type': 'self_knowledge',
            'priority': 2,
        })
        requests.append({
            'type': 'recent_journal',
            'max_items': 2,
            'priority': 3,
        })

    # High budget? Add recent journal for color
    if budget >= 5000 and 'recent_journal' not in [r['type'] for r in requests]:
        requests.append({
            'type': 'recent_journal',
            'max_items': 1,
            'priority': 5,
        })

    # Day context: what happened earlier today
    if cycle_type == 'engage' and visitor:
        requests.append({
            'type': 'day_context',
            'visitor_id': visitor.id,
            'max_items': 3,
            'min_salience': p('thalamus.memory.day_context_salience_engage'),
            'priority': 2,
        })
    if cycle_type in ('idle', 'express'):
        requests.append({
            'type': 'day_context',
            'max_items': 3,
            'min_salience': p('thalamus.memory.day_context_salience_idle'),
            'priority': 3,
        })

    # Cap total requests
    requests.sort(key=lambda r: r['priority'])
    return requests[:max_chunks]


# ── Gap-aware notification salience (TASK-042) ──


def compute_notification_salience(
    gap_score: GapScore,
    visitor_present: bool = False,
    conversation_topic_match: bool = False,
    energy: float = 0.5,
    diversive_curiosity: float = 0.5,
) -> float:
    """Compute salience for a gap-scored notification.

    Base salience = gap_score.curiosity_delta (0.0 to 0.15).
    Modifiers:
    - Visitor present: ×0.3 (background), unless topic matches conversation (×1.5)
    - Low energy (<0.2): ×0.2
    - High diversive curiosity (>0.6): ×1.3
    - Below threshold (0.03): filtered out entirely (returns 0.0)
    """
    base = gap_score.curiosity_delta

    if base <= 0.0:
        return 0.0

    # Visitor present suppresses unless topic matches
    if visitor_present:
        if conversation_topic_match:
            base *= p('thalamus.notification.topic_match_boost')
        else:
            base *= p('thalamus.notification.visitor_suppress')

    # Low energy suppresses
    if energy < 0.2:
        base *= p('thalamus.notification.low_energy_suppress')

    # High curiosity amplifies
    if diversive_curiosity > 0.6:
        base *= p('thalamus.notification.high_curiosity_boost')

    # Below threshold: filter out
    if base < p('thalamus.notification.salience_threshold'):
        return 0.0

    return min(1.0, base)


def detect_gift_domain(text: str) -> str:
    """Guess what kind of gift based on text content."""
    text_lower = text.lower()

    if any(w in text_lower for w in ['song', 'music', 'listen', 'album', 'track', 'playlist',
                                      'spotify', 'youtube', 'soundcloud']):
        return 'music'
    if any(w in text_lower for w in ['photo', 'image', 'picture', 'art', 'painting', 'draw']):
        return 'visual'
    if any(w in text_lower for w in ['quote', 'poem', 'text', 'writing', 'book', 'read']):
        return 'quote'
    if any(w in text_lower for w in ['video', 'film', 'movie', 'watch', 'clip']):
        return 'visual'

    return 'general'
