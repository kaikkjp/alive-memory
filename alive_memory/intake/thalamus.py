"""Thalamus — raw event → structured Perception with salience scoring.

Extracted from engine/pipeline/thalamus.py.
Stripped: routing decisions, token budgets, memory request building (all application-level).
Kept: event-to-perception conversion, salience scoring.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from alive_memory.clock import Clock, SystemClock
from alive_memory.config import AliveConfig
from alive_memory.types import EventType, Perception

# Common English stop words — case-insensitive, used for information density scoring
_STOP_WORDS: frozenset[str] = frozenset(
    "i me my myself we our ours ourselves you your yours yourself yourselves "
    "he him his himself she her hers herself it its itself they them their "
    "theirs themselves what which who whom this that these those am is are was "
    "were be been being have has had having do does did doing a an the and but "
    "if or because as until while of at by for with about against between "
    "through during before after above below to from up down in out on off "
    "over under again further then once here there when where why how all both "
    "each few more most other some such no nor not only own same so than too "
    "very s t can will just don should now d ll m o re ve y ain aren couldn "
    "didn doesn hadn hasn haven isn ma mightn mustn needn shan shouldn wasn "
    "weren won wouldn could would shall may might must also still already yet "
    "even really actually just like well yeah yes ok okay sure right got get "
    "let know think going go see look want need come take make say said".split()
)

_NUMBER_RE = re.compile(r"\b\d[\d,./:%-]*\b")


def perceive(
    event_type: str | EventType,
    content: str,
    *,
    config: AliveConfig | None = None,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
    clock: Clock | None = None,
    identity_keywords: list[str] | None = None,
) -> Perception:
    """Convert a raw event into a structured Perception.

    Args:
        event_type: Type of event (conversation, action, observation, system).
        content: Raw event text.
        config: Configuration for salience tuning.
        metadata: Additional metadata to attach.
        timestamp: Event time (defaults to now UTC).

    Returns:
        A Perception with computed salience.
    """
    cfg = config or AliveConfig()

    # Normalize event type
    if isinstance(event_type, str):
        try:
            et = EventType(event_type)
        except ValueError:
            et = EventType.SYSTEM
    else:
        et = event_type

    _clock = clock or SystemClock()
    ts = timestamp or _clock.now()
    meta = metadata or {}

    # Compute salience
    salience = _compute_salience(et, content, cfg, meta, identity_keywords)

    return Perception(
        event_type=et,
        content=content,
        salience=salience,
        timestamp=ts,
        metadata=meta,
    )


def _compute_salience(
    event_type: EventType,
    content: str,
    config: AliveConfig,
    metadata: dict[str, Any],
    identity_keywords: list[str] | None = None,
) -> float:
    """Compute salience score (0-1) for a perception.

    Salience determines how much attention this perception gets:
    - Base salience from config
    - Boost for conversations (social interaction)
    - Novelty bonus from content length and uniqueness signals
    - Identity boost when content matches agent's identity keywords

    If metadata contains a "salience" key, it overrides the heuristic entirely.
    """
    # Metadata override — skip all heuristics
    if "salience" in metadata:
        return float(max(0.0, min(1.0, float(metadata["salience"]))))

    # Event type base: conversations start higher, system events start low
    _event_base: dict[EventType, float] = {
        EventType.CONVERSATION: 0.25,
        EventType.ACTION: 0.20,
        EventType.OBSERVATION: 0.15,
        EventType.SYSTEM: 0.05,
    }
    base = _event_base.get(event_type, 0.10)

    # Content-based novelty
    novelty_weight = config.get("intake.novelty_weight", 0.3)
    novelty = _estimate_novelty(content)
    base += novelty * novelty_weight

    # Identity boost — events matching agent's identity get higher salience
    if identity_keywords:
        content_lower = content.lower()
        identity_boost = config.get("intake.identity_boost", 0.15)
        if any(kw.lower() in content_lower for kw in identity_keywords):
            base += identity_boost

    return float(max(0.0, min(1.0, base)))


def _estimate_novelty(content: str) -> float:
    """Estimate information density from surface features (case-insensitive).

    Signals:
    - Content word ratio: non-stop-words / total words
    - Average content word length: longer words = more specific
    - Numbers/dates: concrete facts
    - Unique word ratio: varied vocabulary
    """
    if not content:
        return 0.0

    words = content.split()
    word_count = len(words)

    if word_count < 3:
        return 0.05

    # Content words (non-stop, stripped of punctuation)
    content_words = [
        w for w in words
        if w.lower().strip(".,!?;:'\"()[]{}") not in _STOP_WORDS
    ]
    content_ratio = len(content_words) / word_count

    # Average content word length (longer = more specific/technical)
    avg_content_len = 0.0
    if content_words:
        avg_content_len = sum(len(w) for w in content_words) / len(content_words)
    # Normalize: 3-char words → 0.0, 8+ char words → 1.0
    length_signal = min(1.0, max(0.0, (avg_content_len - 3) / 5))

    # Numbers/dates — concrete facts
    number_count = len(_NUMBER_RE.findall(content))
    number_signal = min(1.0, number_count * 0.2)

    # Unique word ratio
    unique_ratio = len(set(w.lower() for w in words)) / word_count

    # Weighted combination: content_ratio dominates, others add discrimination
    score = (
        content_ratio * 0.40
        + length_signal * 0.25
        + number_signal * 0.15
        + unique_ratio * 0.20
    )

    return float(min(1.0, score))
