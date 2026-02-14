"""Sensorium — convert raw events into diegetic perceptions. No LLM."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
import clock
from models.event import Event
from models.state import DrivesState, Visitor
import db


@dataclass
class Perception:
    p_type: str
    source: str
    ts: datetime
    content: str
    features: dict = field(default_factory=dict)
    salience: float = 0.5


async def build_perceptions(unread_events: list[Event], drives: DrivesState,
                           recent_fidgets: list = None,
                           focus_context=None) -> list[Perception]:
    """Convert raw events into diegetic perceptions. No LLM.

    focus_context: Optional ArbiterFocus. When present, a focus perception
    is injected at salience=1.0 for the arbiter's chosen focus.
    """

    perceptions = []

    # ── Focus perception injection (from arbiter) ──
    if focus_context and focus_context.payload:
        focus_p = _build_focus_perception(focus_context)
        if focus_p:
            perceptions.append(focus_p)

    for event in unread_events:
        if event.event_type == 'visitor_speech':
            vid = event.source.split(':')[1] if ':' in event.source else event.source
            visitor = await db.get_visitor(vid)

            text = event.payload.get('text', '')

            # Check if visitor is referencing a fidget she doesn't remember
            fidget_perception = check_fidget_reference(text, recent_fidgets)
            if fidget_perception:
                perceptions.append(fidget_perception)

            p = Perception(
                p_type='visitor_speech',
                source=event.source,
                ts=event.ts,
                content=text,
                features=extract_features(text),
                salience=calculate_salience(event, drives, visitor),
            )
            perceptions.append(p)

        elif event.event_type == 'visitor_connect':
            vid = event.source.split(':')[1] if ':' in event.source else event.source
            visitor = await db.get_visitor(vid)
            trust = visitor.trust_level if visitor else 'stranger'

            if trust == 'stranger':
                content = "Someone new enters the shop."
            elif trust == 'returner':
                content = "Someone who's been here before walks in."
            elif trust == 'regular':
                name = visitor.name or "a familiar face"
                content = f"{name} is back."
            else:
                name = visitor.name or "someone I know well"
                content = f"{name} walks in. Something shifts."

            p = Perception(
                p_type='visitor_connect',
                source=event.source,
                ts=event.ts,
                content=content,
                features={'is_arrival': True, 'trust_level': trust},
                salience=calculate_connect_salience(drives, trust),
            )
            perceptions.append(p)

        elif event.event_type == 'visitor_disconnect':
            vid = event.source.split(':')[1] if ':' in event.source else event.source
            visitor = await db.get_visitor(vid)
            name = visitor.name if visitor and visitor.name else "they"
            p = Perception(
                p_type='visitor_disconnect',
                source=event.source,
                ts=event.ts,
                content=f"{name} left.",
                features={'is_departure': True},
                salience=0.4,
            )
            perceptions.append(p)

        elif event.event_type == 'ambient_discovery':
            title = event.payload.get('title', 'something')
            drop_type = event.payload.get('type', 'text')
            if drop_type == 'url':
                content = f"Something appeared on the counter: {title}"
            else:
                content = f'Something appeared on the counter: "{title}"'
            p = Perception(
                p_type='ambient_discovery',
                source='world',
                ts=event.ts,
                content=content,
                features={
                    'contains_gift': True,
                    'contains_url': drop_type == 'url',
                    'urls': [event.payload['url']] if event.payload.get('url') else [],
                },
                salience=0.5,
            )
            perceptions.append(p)

        elif event.event_type == 'ambient_weather':
            p = Perception(
                p_type='ambient_weather',
                source='ambient',
                ts=event.ts,
                content=event.payload.get('diegetic_text', 'The weather outside.'),
                features={'is_weather': True, **event.payload},
                salience=0.1,
            )
            perceptions.append(p)

    # Add ambient perception
    perceptions.append(build_ambient_perception(drives))

    # Sort by salience, cap at focus(1) + background(3)
    perceptions.sort(key=lambda p: p.salience, reverse=True)
    return perceptions[:4]


def extract_features(text: str) -> dict:
    """Deterministic feature extraction. No LLM."""
    urls = re.findall(r'https?://\S+', text)

    return {
        'contains_question': '?' in text,
        'contains_gift': bool(urls) or any(w in text.lower() for w in [
            'gift', 'brought', 'for you', 'found this', 'listen to',
            'check this', 'look at', 'sharing', 'recommend'
        ]),
        'contains_url': bool(urls),
        'urls': urls,
        'contains_name_question': any(w in text.lower() for w in [
            'your name', 'what should i call', 'who are you'
        ]),
        'contains_personal_question': any(w in text.lower() for w in [
            'how are you', 'how do you feel', 'what do you think about',
            'tell me about yourself', 'where are you from'
        ]),
        'word_count': len(text.split()),
        'is_short': len(text.split()) <= 3,
    }


def calculate_salience(event: Event, drives: DrivesState,
                       visitor: Visitor = None) -> float:
    """Salience = how much she should care about this input."""
    base = 0.5

    text = event.payload.get('text', '')
    features = extract_features(text)

    # Trust amplifies salience
    trust_bonus = {'stranger': 0.0, 'returner': 0.1, 'regular': 0.2, 'familiar': 0.3}
    base += trust_bonus.get(visitor.trust_level if visitor else 'stranger', 0.0)

    # Gifts are always interesting
    if features['contains_gift']:
        base += 0.2

    # Questions demand attention
    if features['contains_question']:
        base += 0.1

    # Personal questions are high stakes
    if features['contains_personal_question'] or features['contains_name_question']:
        base += 0.15

    # Social hunger amplifies visitor salience
    if drives.social_hunger > 0.7:
        base += 0.15

    # Low energy dampens salience
    if drives.energy < 0.3:
        base -= 0.1

    return max(0.0, min(1.0, base))


def calculate_connect_salience(drives: DrivesState, trust_level: str) -> float:
    """Salience for visitor_connect — how much she cares about a new arrival.

    Factors: trust level, social hunger, current absorption (expression_need).
    A familiar face when she's lonely = high salience.
    A stranger when she's absorbed in writing = low salience.
    """
    base = 0.3

    # Trust amplifies: familiar faces pull harder
    trust_bonus = {'stranger': 0.0, 'returner': 0.15, 'regular': 0.3, 'familiar': 0.45}
    base += trust_bonus.get(trust_level, 0.0)

    # Social hunger: lonely = more drawn to visitors
    if drives.social_hunger > 0.7:
        base += 0.2
    elif drives.social_hunger > 0.4:
        base += 0.1

    # Absorption penalty: if she's deep in expression, arrivals matter less
    if drives.expression_need > 0.7:
        base -= 0.15

    # Low energy dampens attention to arrivals
    if drives.energy < 0.3:
        base -= 0.1

    return max(0.0, min(1.0, base))


def build_ambient_perception(drives: DrivesState) -> Perception:
    """Build ambient perception from room state and time."""
    from datetime import datetime, timezone
    from db import JST
    hour = clock.now().hour

    if 5 <= hour < 10:
        time_feel = "Morning light through the windows."
    elif 10 <= hour < 15:
        time_feel = "Midday. The shop is bright."
    elif 15 <= hour < 18:
        time_feel = "Afternoon. The light is getting warm."
    elif 18 <= hour < 21:
        time_feel = "Evening. The shop is quiet."
    else:
        time_feel = "Late. The shop should probably be closed."

    return Perception(
        p_type='ambient',
        source='ambient',
        ts=clock.now_utc(),
        content=time_feel,
        features={'is_ambient': True},
        salience=0.1,
    )


# ── Fidget reference detection ──
# Maps fidget behavior keys to keywords a visitor might use when referencing them.
FIDGET_KEYWORDS = {
    'adjusts_glasses': ['glasses', 'spectacles', 'adjust'],
    'looks_at_object': ['picked up', 'pick up', 'shelf', 'turns it over'],
    'sips_tea': ['tea', 'sip', 'drink', 'cup'],
    'turns_page': ['page', 'reading', 'book'],
    'glances_at_window': ['window', 'looking outside', 'staring out'],
    'touches_shelf': ['shelf', 'fingers', 'trailing'],
    'examines_item': ['holding', 'held', 'looking at', 'studying', 'up to the light'],
}


FIDGET_RECENCY_SECONDS = 300  # only match fidgets from the last 5 minutes


def check_fidget_reference(text: str, recent_fidgets: list = None) -> Perception | None:
    """Check if visitor speech references a recent fidget behavior.

    If matched, returns a fidget_mismatch perception — she becomes aware
    that the visitor saw her do something she doesn't remember doing.
    """
    if not recent_fidgets or not text:
        return None

    text_lower = text.lower()
    now = clock.now_utc()

    for behavior_key, description, ts in recent_fidgets:
        # Skip stale fidgets outside the recency window
        if ts and (now - ts).total_seconds() > FIDGET_RECENCY_SECONDS:
            continue
        keywords = FIDGET_KEYWORDS.get(behavior_key, [])
        for keyword in keywords:
            if keyword in text_lower:
                return Perception(
                    p_type='fidget_mismatch',
                    source='self',
                    ts=clock.now_utc(),
                    content=(
                        f"The visitor describes seeing you: {description} "
                        f"You don't remember doing this."
                    ),
                    features={
                        'is_fidget_mismatch': True,
                        'fidget_key': behavior_key,
                        'fidget_description': description,
                    },
                    salience=0.4,  # below speech so it augments, never replaces focus
                )

    return None


# ── Focus perception building (from arbiter) ──

def _build_focus_perception(focus_context) -> Perception | None:
    """Build a focus perception from an ArbiterFocus.

    Uses dedicated p_types (consume_focus, thread_focus, news_focus) to
    avoid branch collisions in existing Thalamus routing logic.
    """
    if not focus_context or not focus_context.payload:
        return None

    payload = focus_context.payload
    now = clock.now_utc()

    if focus_context.channel == 'consume':
        return Perception(
            p_type='consume_focus',
            source='self',
            ts=now,
            content=f"I'm reading: {payload.get('title', 'something')}",
            features={
                'is_consumption': True,
                'focus_channel': 'consume',
                **payload,
            },
            salience=1.0,
        )

    elif focus_context.channel == 'thread':
        return Perception(
            p_type='thread_focus',
            source='self',
            ts=now,
            content=f"Thinking about: {payload.get('title', 'something')}",
            features={
                'is_thread_focus': True,
                'focus_channel': 'thread',
                **payload,
            },
            salience=1.0,
        )

    elif focus_context.channel == 'news':
        return Perception(
            p_type='news_focus',
            source='feed',
            ts=now,
            content=payload.get('headline', payload.get('title', '')),
            features={
                'is_news': True,
                'focus_channel': 'news',
                **payload,
            },
            salience=1.0,
        )

    return None
