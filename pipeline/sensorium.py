"""Sensorium — convert raw events into diegetic perceptions. No LLM."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
import clock
from models.event import Event
from models.pipeline import TextFragment, GapScore
from models.state import DrivesState, Visitor
from pipeline.notifications import get_notifications, format_notifications_text
from pipeline.gap_detector import (
    detect_gaps, format_gap_annotation, EmbeddingIndex,
)
from db.parameters import p, p_or
import db


@dataclass
class Perception:
    p_type: str
    source: str
    ts: datetime
    content: str
    features: dict = field(default_factory=dict)
    salience: float = 0.5


# ── TASK-087: Channel detection helpers ──

DIGITAL_CHANNEL_PREFIXES = {'tg_': 'Telegram', 'x_': 'X'}


def _detect_channel(visitor_id: str) -> str | None:
    """Return platform name if visitor_id is from a digital channel, else None."""
    for prefix, platform in DIGITAL_CHANNEL_PREFIXES.items():
        if visitor_id.startswith(prefix):
            return platform
    return None


async def build_perceptions(unread_events: list[Event], drives: DrivesState,
                           recent_fidgets: list = None,
                           focus_context=None,
                           embedding_index: EmbeddingIndex = None,
                           fragment_embeddings: dict = None,
                           *, world=None) -> list[Perception]:
    """Convert raw events into diegetic perceptions. No LLM.

    focus_context: Optional ArbiterFocus. When present, a focus perception
    is injected at salience=1.0 for the arbiter's chosen focus.
    embedding_index: Optional EmbeddingIndex for gap detection (TASK-042).
    fragment_embeddings: Optional dict mapping source_id -> embedding vector.
    """

    perceptions = []
    # Collect TextFragments for gap detection (TASK-042)
    gap_fragments: list[TextFragment] = []

    # ── Focus perception injection (from arbiter) ──
    if focus_context and focus_context.payload:
        focus_perc = _build_focus_perception(focus_context)
        if focus_perc:
            perceptions.append(focus_perc)

    for event in unread_events:
        if event.event_type == 'visitor_speech':
            vid = event.source.split(':')[1] if ':' in event.source else event.source
            visitor = await db.get_visitor(vid)

            text = event.payload.get('text', '')

            # Check if visitor is referencing a fidget she doesn't remember
            fidget_perception = check_fidget_reference(text, recent_fidgets)
            if fidget_perception:
                perceptions.append(fidget_perception)

            # TASK-042: Create TextFragment for visitor speech gap detection
            if text and embedding_index:
                gap_fragments.append(TextFragment(
                    text=text,
                    source_type='visitor_speech',
                    source_id=event.id if hasattr(event, 'id') else vid,
                ))

            # TASK-095 v2: Manager messages get trusted human framing
            is_manager = event.payload.get('source') == 'manager'
            if is_manager:
                perc = Perception(
                    p_type='manager_speech',
                    source=event.source,
                    ts=event.ts,
                    content=f"Your trusted human speaks: \"{text}\"",
                    features={**extract_features(text), 'is_manager': True},
                    salience=calculate_salience(event, drives, visitor),
                )
            # TASK-087: Digital channels get different perception type + framing
            elif (channel := _detect_channel(vid)):
                name = visitor.name if visitor and visitor.name else vid
                perc = Perception(
                    p_type='digital_message',
                    source=event.source,
                    ts=event.ts,
                    content=f"A message on {channel} from {name}: \"{text}\"",
                    features={**extract_features(text), 'channel': channel, 'is_digital': True},
                    salience=calculate_salience(event, drives, visitor),
                )
            else:
                perc = Perception(
                    p_type='visitor_speech',
                    source=event.source,
                    ts=event.ts,
                    content=text,
                    features=extract_features(text),
                    salience=calculate_salience(event, drives, visitor),
                )
            perceptions.append(perc)

        elif event.event_type == 'visitor_connect':
            vid = event.source.split(':')[1] if ':' in event.source else event.source
            visitor = await db.get_visitor(vid)
            trust = visitor.trust_level if visitor else 'stranger'

            # TASK-087: Digital channels don't "enter the shop"
            channel = _detect_channel(vid)
            if channel:
                name = visitor.name if visitor and visitor.name else "someone"
                content = f"A new conversation on {channel} from {name}."
                perc = Perception(
                    p_type='digital_connect',
                    source=event.source,
                    ts=event.ts,
                    content=content,
                    features={'is_arrival': True, 'trust_level': trust, 'channel': channel, 'is_digital': True},
                    salience=calculate_connect_salience(drives, trust),
                )
            else:
                has_physical = world.has_physical_space if world else True
                if trust == 'stranger':
                    content = ("Someone new enters the shop." if has_physical
                               else "Someone new reaches out.")
                elif trust == 'returner':
                    content = ("Someone who's been here before walks in." if has_physical
                               else "Someone who's been here before reaches out.")
                elif trust == 'regular':
                    name = visitor.name or "a familiar face"
                    content = f"{name} is back."
                else:
                    name = visitor.name or "someone I know well"
                    content = (f"{name} walks in. Something shifts." if has_physical
                               else f"{name} is here. Something shifts.")

                perc = Perception(
                    p_type='visitor_connect',
                    source=event.source,
                    ts=event.ts,
                    content=content,
                    features={'is_arrival': True, 'trust_level': trust},
                    salience=calculate_connect_salience(drives, trust),
                )
            perceptions.append(perc)

        elif event.event_type == 'visitor_disconnect':
            vid = event.source.split(':')[1] if ':' in event.source else event.source
            visitor = await db.get_visitor(vid)
            name = visitor.name if visitor and visitor.name else "they"

            # TASK-087: Digital channels don't "leave the shop"
            channel = _detect_channel(vid)
            if channel:
                perc = Perception(
                    p_type='digital_disconnect',
                    source=event.source,
                    ts=event.ts,
                    content=f"{name} went quiet on {channel}.",
                    features={'is_departure': True, 'channel': channel, 'is_digital': True},
                    salience=0.2,
                )
            else:
                perc = Perception(
                    p_type='visitor_disconnect',
                    source=event.source,
                    ts=event.ts,
                    content=f"{name} left.",
                    features={'is_departure': True},
                    salience=0.4,
                )
            perceptions.append(perc)

        elif event.event_type == 'ambient_discovery':
            title = event.payload.get('title', 'something')
            drop_type = event.payload.get('type', 'text')
            has_physical = world.has_physical_space if world else True
            if drop_type == 'url':
                content = (f"Something appeared on the counter: {title}" if has_physical
                           else f"Something arrived: {title}")
            else:
                content = (f'Something appeared on the counter: "{title}"' if has_physical
                           else f'Something new: "{title}"')
            perc = Perception(
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
            perceptions.append(perc)

        elif event.event_type == 'ambient_weather':
            perc = Perception(
                p_type='ambient_weather',
                source='ambient',
                ts=event.ts,
                content=event.payload.get('diegetic_text', 'The weather outside.'),
                features={'is_weather': True, **event.payload},
                salience=0.1,
            )
            perceptions.append(perc)

        elif event.event_type == 'meta_controller_adjustment':
            # TASK-090: Character-aligned perception of homeostatic tuning
            adj_list = event.payload.get('adjustments', [])
            content = _build_meta_controller_perception(adj_list)
            if content:
                perc = Perception(
                    p_type='meta_adjustment',
                    source='self',
                    ts=event.ts,
                    content=content,
                    features={
                        'is_homeostatic': True,
                        'adjustment_count': len(adj_list),
                    },
                    salience=0.6,
                )
                perceptions.append(perc)

        elif event.event_type == 'meta_controller_evaluation':
            # TASK-091: Character-aligned perception of evaluation outcomes
            evaluations = event.payload.get('evaluations', [])
            content = _build_evaluation_perception(evaluations)
            if content:
                perc = Perception(
                    p_type='meta_evaluation',
                    source='self',
                    ts=event.ts,
                    content=content,
                    features={
                        'is_homeostatic': True,
                        'is_evaluation': True,
                        'evaluation_count': len(evaluations),
                    },
                    salience=0.6,
                )
                perceptions.append(perc)

        elif event.event_type == 'identity_evolution':
            # TASK-092: Character-aligned perception of identity evolution
            content = _build_identity_evolution_perception(event.payload)
            if content:
                perc = Perception(
                    p_type='identity_evolution',
                    source='self',
                    ts=event.ts,
                    content=content,
                    features={
                        'is_homeostatic': True,
                        'evolution_type': event.payload.get('type', 'unknown'),
                    },
                    salience=0.5,
                )
                perceptions.append(perc)

    # ── Notification injection (TASK-041) + gap detection (TASK-042) ──
    # Surface content titles from the feed as background perceptions.
    # Gap detection scores notifications against her memory for curiosity spikes.
    gap_scores: list[GapScore] = []
    try:
        notifications = await get_notifications()
        if notifications:
            visitor_present = any(
                e.event_type in ('visitor_speech', 'visitor_connect')
                for e in unread_events
            )

            # TASK-042: Create TextFragments for notification gap detection
            for n in notifications:
                gap_fragments.append(TextFragment(
                    text=n.title,
                    source_type='notification',
                    source_id=n.content_id,
                    content_id=n.content_id,
                ))

            # Run gap detection on all fragments (notifications + visitor speech)
            if embedding_index and gap_fragments and fragment_embeddings:
                gap_scores = detect_gaps(
                    gap_fragments, embedding_index, fragment_embeddings or {}
                )

            # Build gap-aware notification text
            notif_gap_scores = {
                gs.fragment.content_id: gs
                for gs in gap_scores
                if gs.fragment.source_type == 'notification' and gs.fragment.content_id
            }
            notif_text = format_notifications_text(
                notifications, visitor_present, gap_scores=notif_gap_scores)
            if notif_text:
                perceptions.append(Perception(
                    p_type='feed_notifications',
                    source='feed',
                    ts=clock.now_utc(),
                    content=notif_text,
                    features={
                        'is_notification': True,
                        'content_ids': [n.content_id for n in notifications],
                        'gap_scores': {
                            gs.fragment.source_id: {
                                'relevance': gs.relevance,
                                'gap_type': gs.gap_type,
                                'curiosity_delta': gs.curiosity_delta,
                            }
                            for gs in gap_scores
                        },
                    },
                    salience=0.3,
                ))

            # TASK-042: Add visitor speech gap annotations to perceptions
            for gs in gap_scores:
                if gs.fragment.source_type == 'visitor_speech' and gs.gap_type == 'partial':
                    annotation = format_gap_annotation(gs)
                    if annotation:
                        perceptions.append(Perception(
                            p_type='visitor_speech_gap',
                            source='self',
                            ts=clock.now_utc(),
                            content=f"Something your visitor said connects to your memory. {annotation}",
                            features={
                                'is_gap_detection': True,
                                'gap_score': gs.curiosity_delta,
                                'gap_type': gs.gap_type,
                            },
                            salience=0.25,
                        ))
    except Exception as e:
        print(f"  [Sensorium] Notification/gap injection failed: {e}")

    # Add ambient perception
    perceptions.append(build_ambient_perception(drives, world=world))

    # Sort by salience, cap at focus(1) + background(5)
    # Increased cap from 4 to 6 to accommodate notifications alongside other perceptions
    perceptions.sort(key=lambda perc: perc.salience, reverse=True)
    return perceptions[:int(p('sensorium.perception.max_count'))]


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
    base = p('sensorium.salience.base')

    text = event.payload.get('text', '')
    features = extract_features(text)

    # Trust amplifies salience (p_or: unknown trust_level falls back to 0.0)
    trust = visitor.trust_level if visitor else 'stranger'
    trust_key = f'sensorium.salience.trust_{trust}'
    base += p_or(trust_key, 0.0)

    # Gifts are always interesting
    if features['contains_gift']:
        base += p('sensorium.salience.gift_bonus')

    # Questions demand attention
    if features['contains_question']:
        base += p('sensorium.salience.question_bonus')

    # Personal questions are high stakes
    if features['contains_personal_question'] or features['contains_name_question']:
        base += p('sensorium.salience.personal_bonus')

    # Social hunger amplifies visitor salience
    if drives.social_hunger > 0.7:
        base += p('sensorium.salience.social_hunger_bonus')

    # Low energy dampens salience
    if drives.energy < 0.3:
        base += p('sensorium.salience.low_energy_penalty')

    return max(0.0, min(1.0, base))


def calculate_connect_salience(drives: DrivesState, trust_level: str) -> float:
    """Salience for visitor_connect — how much she cares about a new arrival.

    Factors: trust level, social hunger, current absorption (expression_need).
    A familiar face when she's lonely = high salience.
    A stranger when she's absorbed in writing = low salience.
    """
    base = p('sensorium.connect.base')

    # Trust amplifies: familiar faces pull harder (p_or: unknown trust falls back to 0.0)
    trust_key = f'sensorium.connect.trust_{trust_level}'
    base += p_or(trust_key, 0.0)

    # Social hunger: lonely = more drawn to visitors
    if drives.social_hunger > 0.7:
        base += p('sensorium.connect.social_hunger_high_bonus')
    elif drives.social_hunger > 0.4:
        base += p('sensorium.connect.social_hunger_mid_bonus')

    # Absorption penalty: if she's deep in expression, arrivals matter less
    if drives.expression_need > 0.7:
        base += p('sensorium.connect.expression_penalty')

    # Low energy dampens attention to arrivals
    if drives.energy < 0.3:
        base += p('sensorium.connect.low_energy_penalty')

    return max(0.0, min(1.0, base))


def build_ambient_perception(drives: DrivesState, *, world=None) -> Perception:
    """Build ambient perception from room state and time."""
    from datetime import datetime, timezone
    from db import JST
    has_physical = world.has_physical_space if world else True
    hour = clock.now().hour

    if has_physical:
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
    else:
        if 5 <= hour < 10:
            time_feel = "Morning. Still early."
        elif 10 <= hour < 15:
            time_feel = "Midday."
        elif 15 <= hour < 18:
            time_feel = "Afternoon."
        elif 18 <= hour < 21:
            time_feel = "Evening. Getting late."
        else:
            time_feel = "Late. The day is almost over."

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
        if ts and (now - ts).total_seconds() > p('sensorium.fidget.recency_seconds'):
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
                    salience=p('sensorium.fidget.mismatch_salience'),
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


# ── Meta-controller perception (TASK-090) ──

# Maps metric targets to diegetic descriptions she can feel
_METRIC_FEELINGS: dict[str, tuple[str, str]] = {
    'initiative_rate': ("I've been less active than usual", "I've been restless lately"),
    'emotional_range': ("things have felt flat", "my feelings have been running wild"),
}


def _build_meta_controller_perception(adjustments: list[dict]) -> str | None:
    """Build a character-aligned perception of homeostatic parameter adjustment.

    She doesn't see raw numbers — she feels a vague shift, like waking up
    slightly different. The perception uses diegetic language consistent
    with the Shopkeeper's voice.
    """
    if not adjustments:
        return None

    parts = []
    for adj in adjustments:
        target = adj.get('target_metric', '')
        old_val = adj.get('old_value', 0)
        new_val = adj.get('new_value', 0)

        # Try to find a diegetic description
        feelings = _METRIC_FEELINGS.get(target)
        if feelings:
            if new_val > old_val:
                parts.append(feelings[0])  # low metric → raising param
            else:
                parts.append(feelings[1])  # high metric → lowering param
        else:
            parts.append("something shifted in how I approach things")

    if len(parts) == 1:
        return f"{parts[0].capitalize()}, so something adjusted — subtly."
    else:
        joined = " and ".join(parts)
        return f"{joined.capitalize()} — something recalibrated overnight."


# ── Evaluation perception (TASK-091) ──

# Diegetic perception templates for evaluation outcomes
_EVAL_TEMPLATES = {
    'improved': "A subtle shift I noticed recently seems to be working well. I feel more balanced.",
    'degraded': "I tried approaching things differently, but it didn't feel right. I've settled back to how I was before.",
    'neutral': "Something I adjusted recently doesn't seem to have made much difference either way.",
    'side_effect': "Something I changed had unexpected consequences. I'm reverting to be safe.",
}


def _build_evaluation_perception(evaluations: list[dict]) -> str | None:
    """Build a character-aligned perception of experiment evaluation outcomes.

    She feels the result of her overnight adjustments — not the numbers,
    but whether things feel better, worse, or the same.
    """
    if not evaluations:
        return None

    # Group by outcome type
    outcomes = {}
    for ev in evaluations:
        outcome = ev.get('outcome', 'neutral')
        outcomes.setdefault(outcome, []).append(ev)

    # Priority: side_effect > degraded > improved > neutral
    if 'side_effect' in outcomes:
        return _EVAL_TEMPLATES['side_effect']
    if 'degraded' in outcomes:
        return _EVAL_TEMPLATES['degraded']
    if 'improved' in outcomes:
        return _EVAL_TEMPLATES['improved']
    return _EVAL_TEMPLATES['neutral']


# ── Identity evolution perceptions (TASK-092) ──

_EVOLUTION_TEMPLATES = {
    'accepted': "Something about me has changed gradually... it feels natural, "
                "like a quiet shift I barely noticed until now.",
    'corrected': "Something feels more settled now, like I've found my footing again.",
}


def _build_identity_evolution_perception(payload: dict) -> str | None:
    """Build a character-aligned perception of identity evolution decisions.

    She feels the outcome of evolution — acceptance feels like growth,
    correction feels like settling back to center. Defers are silent.
    """
    evo_type = payload.get('type', '')
    if evo_type in _EVOLUTION_TEMPLATES:
        return _EVOLUTION_TEMPLATES[evo_type]
    return None
