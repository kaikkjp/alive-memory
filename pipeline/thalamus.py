"""Thalamus — deterministic code routing. No LLM."""

from dataclasses import dataclass, field
from models.state import DrivesState, EngagementState, Visitor
from pipeline.sensorium import Perception
import clock
import db


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
) -> RoutingDecision:
    """Deterministic routing. No LLM. Code only."""

    if not perceptions:
        return await autonomous_routing(drives)

    focus = perceptions[0]  # highest salience
    background = perceptions[1:4]

    # Determine cycle type
    if focus.p_type == 'visitor_speech':
        cycle_type = 'engage'
    elif focus.p_type == 'visitor_connect':
        cycle_type = 'engage'
    elif focus.p_type == 'visitor_disconnect':
        cycle_type = 'idle'  # she's alone now — reflect, don't engage
    elif focus.p_type == 'visitor_silence':
        cycle_type = 'engage'  # silence is still part of conversation
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
    elif drives.expression_need > 0.7:
        cycle_type = 'express'
    elif drives.rest_need > 0.7:
        cycle_type = 'rest'
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


async def autonomous_routing(drives: DrivesState) -> RoutingDecision:
    """Routing when no perceptions — she's alone."""
    if drives.expression_need > 0.7:
        cycle_type = 'express'
    elif drives.rest_need > 0.7:
        cycle_type = 'rest'
    else:
        cycle_type = 'idle'

    focus = Perception(
        p_type='internal',
        source='self',
        ts=clock.now_utc(),
        content='No one is here. The shop is quiet.',
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
            'min_salience': 0.5,
            'priority': 3,
        })

    return RoutingDecision(
        cycle_type=cycle_type,
        focus=focus,
        background=[],
        memory_requests=memory_requests,
        token_budget=3000,
    )


async def get_token_budget(salience: float, drives: DrivesState) -> int:
    """Dynamic budget based on salience. Flashbulb moments get more context."""

    flashbulbs_today = await db.get_flashbulb_count_today()
    DAILY_FLASHBULB_LIMIT = 5

    if salience > 0.8:
        if flashbulbs_today < DAILY_FLASHBULB_LIMIT:
            return 10000   # flashbulb: full memory palace
        else:
            return 5000    # budget exhausted, fall back

    if salience > 0.6:
        return 5000        # deep conversation

    return 3000            # casual


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
            'max_items': 5 if budget >= 5000 else 3,
            'min_weight': 0.3 if budget >= 5000 else 0.6,
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
            'min_salience': 0.3,
            'priority': 2,
        })
    if cycle_type in ('idle', 'express'):
        requests.append({
            'type': 'day_context',
            'max_items': 3,
            'min_salience': 0.5,
            'priority': 3,
        })

    # Cap total requests
    requests.sort(key=lambda r: r['priority'])
    return requests[:max_chunks]


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
