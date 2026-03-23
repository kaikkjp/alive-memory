"""Thalamus — multi-axis salience scorer with habituation.

Stateful (maintains habituation buffer).  No storage dependency.  No LLM.

Usage::

    thalamus = Thalamus()
    result = thalamus.perceive(event)
    print(result.band, result.salience, result.reasons)
"""

from __future__ import annotations

from datetime import UTC, datetime

from alive_cognition.channels import (
    ChannelContext,
    score_impact,
    score_relevance,
    score_surprise,
    score_urgency,
)
from alive_cognition.habituation import HabituationBuffer
from alive_cognition.overrides import check_overrides
from alive_cognition.types import (
    ChannelScores,
    ChannelWeights,
    EventSchema,
    SalienceBand,
    ScoredPerception,
)
from alive_memory.config import AliveConfig
from alive_memory.types import DriveState, MoodState


class Thalamus:
    """Multi-axis salience scorer with habituation.

    Stateful — maintains habituation buffer.
    No storage dependency.  No LLM.
    """

    def __init__(
        self,
        config: AliveConfig | None = None,
        weights: ChannelWeights | None = None,
        identity_keywords: list[str] | None = None,
    ) -> None:
        self._config = config or AliveConfig()
        self._weights = weights or ChannelWeights()
        self._habituation = HabituationBuffer(
            max_size=self._config.get("thalamus.habituation_buffer_size", 100),
            decay_rate=self._config.get("thalamus.habituation_decay_rate", 0.85),
        )
        self._context = ChannelContext(identity_keywords=identity_keywords)

    def perceive(self, event: EventSchema) -> ScoredPerception:
        """Score an event across all channels, apply modifiers, assign band.

        Pipeline:
          1. Check hard overrides (force high/low)
          2. Score each channel
          3. Compute weighted composite
          4. Apply habituation novelty decay
          5. Assign band from final score
          6. Record event in habituation buffer
          7. Return ScoredPerception with full breakdown
        """
        ts = event.timestamp or datetime.now(UTC)

        # 1. Hard overrides
        override = check_overrides(event)

        # 2. Score channels
        channels, all_reasons = self._score_channels(event)

        # 3. Weighted composite
        base = self._weighted_composite(channels)

        # 4. Habituation
        novelty = self._habituation.novelty_factor(event)
        final = max(0.0, min(1.0, base * novelty))

        # 5. Metadata salience override (highest priority, backward compat)
        if "salience" in event.metadata:
            final = float(max(0.0, min(1.0, float(event.metadata["salience"]))))
            band = self._assign_band(final)
            reasons = ["salience override from metadata"] + all_reasons
        elif override.applied:
            band = override.force_band
            reasons = [override.reason] + all_reasons
        else:
            band = self._assign_band(final)
            reasons = all_reasons

        # 6. Record in habituation buffer
        self._habituation.record(event)

        # 7. Build result
        return ScoredPerception(
            event=event,
            channels=channels,
            salience=final,
            band=band,
            reasons=reasons,
            novelty_factor=novelty,
            timestamp=ts,
        )

    def update_context(
        self,
        *,
        active_goals: list[str] | None = None,
        current_drives: DriveState | None = None,
        current_mood: MoodState | None = None,
        identity_keywords: list[str] | None = None,
    ) -> None:
        """Update context for context-dependent scoring.

        Any parameter left as ``None`` keeps its previous value.
        """
        ctx = self._context
        self._context = ChannelContext(
            active_goals=active_goals if active_goals is not None else ctx.active_goals,
            identity_keywords=(
                identity_keywords if identity_keywords is not None else ctx.identity_keywords
            ),
            current_drives=(current_drives if current_drives is not None else ctx.current_drives),
            current_mood=(current_mood if current_mood is not None else ctx.current_mood),
        )

    def reset_habituation(self) -> None:
        """Clear habituation buffer (e.g., after sleep)."""
        self._habituation.clear()

    # ── Private helpers ──────────────────────────────────────────────

    def _score_channels(self, event: EventSchema) -> tuple[ChannelScores, list[str]]:
        """Score all four channels and collect reasons."""
        rel_score, rel_reasons = score_relevance(event, self._context)
        sur_score, sur_reasons = score_surprise(event, self._context)
        imp_score, imp_reasons = score_impact(event, self._context)
        urg_score, urg_reasons = score_urgency(event, self._context)

        channels = ChannelScores(
            relevance=rel_score,
            surprise=sur_score,
            impact=imp_score,
            urgency=urg_score,
        )
        reasons = rel_reasons + sur_reasons + imp_reasons + urg_reasons
        return channels, reasons

    def _weighted_composite(self, channels: ChannelScores) -> float:
        """Compute the weighted composite salience score."""
        w = self._weights
        return (
            w.relevance * channels.relevance
            + w.surprise * channels.surprise
            + w.impact * channels.impact
            + w.urgency * channels.urgency
        )

    @staticmethod
    def _assign_band(score: float) -> SalienceBand:
        """Map a 0-1 score to a discrete salience band."""
        if score <= 0.30:
            return SalienceBand.DROP
        if score <= 0.70:
            return SalienceBand.STORE
        return SalienceBand.PRIORITIZE
