"""Moment formation — Perception → DayMoment with salience gating.

Records only *salient* moments, not every event.
Deterministic salience scoring (no LLM):
  event type base + drive delta + content richness + mood extremes

Dynamic threshold, dedup guard, lowest-salience eviction.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher

from alive_memory.config import AliveConfig
from alive_memory.intake.affect import compute_valence
from alive_memory.storage.base import BaseStorage
from alive_memory.types import (
    DayMoment,
    DriveState,
    EventType,
    MoodState,
    Perception,
)

# Maximum moments in day memory before eviction kicks in
MAX_DAY_MOMENTS = 30

# Dedup window in minutes — ignore near-duplicate content within this window
DEDUP_WINDOW_MINUTES = 30

# Salience thresholds
BASE_THRESHOLD = 0.35
MAX_THRESHOLD = 0.55

# Event type base salience scores
_EVENT_BASE_SALIENCE: dict[EventType, float] = {
    EventType.CONVERSATION: 0.40,
    EventType.ACTION: 0.30,
    EventType.OBSERVATION: 0.25,
    EventType.SYSTEM: 0.15,
}


async def form_moment(
    perception: Perception,
    mood: MoodState,
    drives: DriveState,
    storage: BaseStorage,
    *,
    previous_drives: DriveState | None = None,
    config: AliveConfig | None = None,
) -> DayMoment | None:
    """Form a DayMoment from a perception, or return None if below threshold.

    Salience scoring is deterministic (no LLM):
      1. Event type base score
      2. Drive delta bonus (change from previous drives)
      3. Content richness
      4. Mood extremes bonus

    Gating:
      - Dynamic threshold rises as day_memory fills up
      - Dedup guard rejects near-duplicates within 30-minute window
      - Eviction removes lowest-salience moment when at MAX_DAY_MOMENTS

    Returns:
        DayMoment if the perception is salient enough, None otherwise.
    """
    cfg = config or AliveConfig()

    # Compute deterministic salience
    salience = _compute_salience(perception, mood, drives, previous_drives)

    # Dynamic threshold: rises from BASE_THRESHOLD → MAX_THRESHOLD as count → MAX
    current_count = await storage.get_day_memory_count()
    fill_ratio = min(1.0, current_count / MAX_DAY_MOMENTS)
    threshold = BASE_THRESHOLD + (MAX_THRESHOLD - BASE_THRESHOLD) * fill_ratio

    if salience < threshold:
        return None

    # Dedup guard: reject near-duplicate content within window
    recent_contents = await storage.get_recent_moment_content(
        window_minutes=DEDUP_WINDOW_MINUTES
    )
    if _is_duplicate(perception.content, recent_contents):
        return None

    # Compute valence
    valence = compute_valence(perception.content, mood)

    # Snapshot drives at this moment
    drive_snapshot = {
        "curiosity": drives.curiosity,
        "social": drives.social,
        "expression": drives.expression,
        "rest": drives.rest,
    }

    moment = DayMoment(
        id=str(uuid.uuid4()),
        content=perception.content,
        event_type=perception.event_type,
        salience=salience,
        valence=valence,
        drive_snapshot=drive_snapshot,
        timestamp=perception.timestamp or datetime.now(timezone.utc),
        metadata=perception.metadata,
    )

    # Eviction: if at capacity, remove lowest-salience moment if new one is better
    if current_count >= MAX_DAY_MOMENTS:
        lowest = await storage.get_lowest_salience_moment()
        if lowest and lowest.salience < salience:
            await storage.delete_moment(lowest.id)
        else:
            return None  # New moment isn't salient enough to justify eviction

    await storage.record_moment(moment)
    return moment


def _compute_salience(
    perception: Perception,
    mood: MoodState,
    drives: DriveState,
    previous_drives: DriveState | None,
) -> float:
    """Deterministic salience scoring.

    Components:
      1. Event type base (0.15-0.40)
      2. Drive delta bonus (0-0.20) — how much drives changed
      3. Content richness (0-0.20) — word count, uniqueness, questions
      4. Mood extremes (0-0.15) — extreme moods make things more salient
    """
    # 1. Event type base
    base = _EVENT_BASE_SALIENCE.get(perception.event_type, 0.20)

    # 2. Drive delta bonus
    drive_delta = 0.0
    if previous_drives:
        deltas = [
            abs(drives.curiosity - previous_drives.curiosity),
            abs(drives.social - previous_drives.social),
            abs(drives.expression - previous_drives.expression),
            abs(drives.rest - previous_drives.rest),
        ]
        drive_delta = min(0.20, sum(deltas) * 0.5)

    # 3. Content richness
    richness = _content_richness(perception.content)

    # 4. Mood extremes — very positive or very negative moods boost salience
    mood_boost = min(0.15, abs(mood.valence) * 0.2 + max(0, mood.arousal - 0.6) * 0.15)

    # Metadata override
    if "salience" in perception.metadata:
        return max(0.0, min(1.0, float(perception.metadata["salience"])))

    return max(0.0, min(1.0, base + drive_delta + richness + mood_boost))


def _content_richness(content: str) -> float:
    """Score content richness (0-0.20).

    Factors: word count, word uniqueness, presence of questions.
    """
    if not content:
        return 0.0

    words = content.split()
    word_count = len(words)

    # Very short = low richness
    if word_count < 3:
        return 0.02

    # Word uniqueness
    unique_ratio = len(set(w.lower() for w in words)) / max(word_count, 1)

    # Length factor (diminishing returns)
    length_factor = min(0.10, word_count * 0.003)

    # Question bonus
    question_bonus = 0.03 if "?" in content else 0.0

    return min(0.20, length_factor + unique_ratio * 0.08 + question_bonus)


def _is_duplicate(content: str, recent_contents: list[str]) -> bool:
    """Check if content is a near-duplicate of recent moments.

    Uses SequenceMatcher for fuzzy matching. Threshold: 0.85 similarity.
    """
    if not recent_contents:
        return False

    content_lower = content.lower().strip()
    for recent in recent_contents:
        ratio = SequenceMatcher(None, content_lower, recent.lower().strip()).ratio()
        if ratio >= 0.85:
            return True
    return False
