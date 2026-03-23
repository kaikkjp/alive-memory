"""In-memory ring buffer for novelty decay.

Tracks recent events and decays salience for repeated/similar input.
Uses content fingerprinting (lowercased word set) and Jaccard similarity.
"""

from __future__ import annotations

import collections
from datetime import datetime

from alive_cognition.types import EventSchema


class HabituationBuffer:
    """Track recent events for novelty decay.

    Suppresses repeated noise without losing awareness entirely.
    Uses content fingerprinting (lowercased, sorted word set) for similarity.
    """

    def __init__(self, max_size: int = 100, decay_rate: float = 0.85) -> None:
        """
        Args:
            max_size: Maximum events in the ring buffer.
            decay_rate: Per-match decay multiplier. Lower = faster habituation.
        """
        self._buffer: collections.deque[tuple[str, str, frozenset[str], datetime | None]] = (
            collections.deque(maxlen=max_size)
        )
        self._decay_rate = decay_rate

    def novelty_factor(self, event: EventSchema) -> float:
        """Returns 0.4-1.0.  Decays if similar events seen recently.

        Similarity check: same source AND same event_type AND
        fingerprint overlap > 0.6.  Each similar recent event multiplies
        the factor by *decay_rate*.  Floor at 0.4 (never fully suppress).
        """
        fp = self._fingerprint(event.content)
        factor = 1.0

        for source, event_type, stored_fp, _ts in self._buffer:
            if source != event.source:
                continue
            if event_type != event.event_type.value:
                continue
            if self._similarity(fp, stored_fp) > 0.6:
                factor *= self._decay_rate

        return max(0.4, factor)

    def record(self, event: EventSchema) -> None:
        """Add event to buffer.  Call AFTER scoring."""
        fp = self._fingerprint(event.content)
        self._buffer.append((event.source, event.event_type.value, fp, event.timestamp))

    def _fingerprint(self, content: str) -> frozenset[str]:
        """Lowercase, split, take unique words as a frozenset."""
        return frozenset(content.lower().split())

    def _similarity(self, fp1: frozenset[str], fp2: frozenset[str]) -> float:
        """Jaccard similarity: |intersection| / |union|."""
        if not fp1 and not fp2:
            return 1.0
        union = fp1 | fp2
        if not union:
            return 1.0
        return len(fp1 & fp2) / len(union)

    def clear(self) -> None:
        """Clear the buffer (e.g., after sleep)."""
        self._buffer.clear()
