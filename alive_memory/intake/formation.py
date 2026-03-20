"""Moment formation — Perception → DayMoment with salience gating.

Records only *salient* moments, not every event.
Deterministic salience scoring (no LLM):
  event type base + drive delta + content richness + mood extremes

Dynamic threshold, dedup guard, lowest-salience eviction.
"""

from __future__ import annotations

import uuid
from difflib import SequenceMatcher

from alive_memory.clock import Clock, SystemClock
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

# Maximum moments in day memory before eviction kicks in.
# Raised from 30 → 500: consolidation costs ~$0.005/day, no budget reason
# for a tight cap. Eviction still works as a safety valve at high counts.
MAX_DAY_MOMENTS = 500

# Dedup window in minutes — ignore near-duplicate content within this window
DEDUP_WINDOW_MINUTES = 30

# Salience thresholds
BASE_THRESHOLD = 0.35
MAX_THRESHOLD = 0.55



async def form_moment(
    perception: Perception,
    mood: MoodState,
    drives: DriveState,
    storage: BaseStorage,
    *,
    previous_drives: DriveState | None = None,
    config: AliveConfig | None = None,
    clock: Clock | None = None,
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
    _clock = clock or SystemClock()

    # Read tunable constants from config (with hardcoded defaults for compat)
    max_day_moments = cfg.get("intake.max_day_moments", MAX_DAY_MOMENTS)
    base_threshold = cfg.get("intake.salience_threshold", BASE_THRESHOLD)
    max_threshold = cfg.get("intake.max_salience_threshold", MAX_THRESHOLD)
    dedup_window = cfg.get("intake.dedup_window_minutes", DEDUP_WINDOW_MINUTES)
    dedup_similarity = cfg.get("intake.dedup_similarity", 0.85)

    # Start from perception's salience (computed by thalamus with content
    # analysis), then layer on drive/mood context signals.
    salience = _adjust_salience(perception, mood, drives, previous_drives)

    # Dynamic threshold: rises from base → max as count → capacity
    current_count = await storage.get_day_memory_count()
    fill_ratio = min(1.0, current_count / max_day_moments)
    threshold = base_threshold + (max_threshold - base_threshold) * fill_ratio

    if salience < threshold:
        return None

    # Dedup guard: reject near-duplicate content within window
    ref_time = _clock.now().isoformat()
    recent_contents = await storage.get_recent_moment_content(
        window_minutes=dedup_window, reference_time=ref_time
    )
    if _is_duplicate(perception.content, recent_contents, threshold=dedup_similarity):
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
        timestamp=perception.timestamp or _clock.now(),
        metadata=perception.metadata,
    )

    # Eviction: if at capacity, remove lowest-salience moment if new one is better
    if current_count >= max_day_moments:
        lowest = await storage.get_lowest_salience_moment()
        if lowest and lowest.salience < salience:
            await storage.delete_moment(lowest.id)
        else:
            return None  # New moment isn't salient enough to justify eviction

    await storage.record_moment(moment)
    return moment


def _adjust_salience(
    perception: Perception,
    mood: MoodState,
    drives: DriveState,
    previous_drives: DriveState | None,
) -> float:
    """Adjust perception salience with drive/mood context.

    Starts from perception.salience (computed by thalamus with content
    analysis: stop word ratio, content word length, numbers, etc.)
    and layers on contextual signals:
      1. Drive delta bonus (0-0.15) — how much drives changed
      2. Mood extremes (0-0.10) — extreme moods make things more salient
    """
    # Metadata override
    if "salience" in perception.metadata:
        return max(0.0, min(1.0, float(perception.metadata["salience"])))

    base = perception.salience

    # Drive delta bonus
    drive_delta = 0.0
    if previous_drives:
        deltas = [
            abs(drives.curiosity - previous_drives.curiosity),
            abs(drives.social - previous_drives.social),
            abs(drives.expression - previous_drives.expression),
            abs(drives.rest - previous_drives.rest),
        ]
        drive_delta = min(0.15, sum(deltas) * 0.5)

    # Mood extremes — very positive or very negative moods boost salience
    mood_boost = min(0.10, abs(mood.valence) * 0.15 + max(0, mood.arousal - 0.6) * 0.10)

    return max(0.0, min(1.0, base + drive_delta + mood_boost))




def _is_duplicate(
    content: str, recent_contents: list[str], *, threshold: float = 0.85
) -> bool:
    """Check if content is a near-duplicate of recent moments.

    Uses SequenceMatcher for fuzzy matching.
    """
    if not recent_contents:
        return False

    content_lower = content.lower().strip()
    for recent in recent_contents:
        ratio = SequenceMatcher(None, content_lower, recent.lower().strip()).ratio()
        if ratio >= threshold:
            return True
    return False
