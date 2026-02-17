"""Tests for thalamus gap-aware notification salience filtering.

TASK-042: Verifies that compute_notification_salience correctly modulates
notification visibility based on state context.
"""

import pytest

from models.pipeline import TextFragment, GapScore
from pipeline.thalamus import (
    compute_notification_salience,
    NOTIFICATION_SALIENCE_THRESHOLD,
)


def _make_gap_score(curiosity_delta=0.10, gap_type='partial', relevance=0.5):
    """Create a GapScore with given curiosity_delta."""
    return GapScore(
        fragment=TextFragment(
            text='Test Article',
            source_type='notification',
            source_id='item-1',
            content_id='item-1',
        ),
        relevance=relevance,
        gap_type=gap_type,
        curiosity_delta=curiosity_delta,
    )


class TestComputeNotificationSalience:
    """compute_notification_salience() modulates notification visibility."""

    def test_base_salience_from_gap(self):
        """Base salience equals curiosity_delta."""
        gs = _make_gap_score(curiosity_delta=0.10)
        salience = compute_notification_salience(gs)
        assert salience > 0.0
        # Without modifiers, base should be close to curiosity_delta
        assert abs(salience - 0.10) < 0.01

    def test_visitor_present_suppresses(self):
        """Salience reduced when visitor present (no topic match)."""
        gs = _make_gap_score(curiosity_delta=0.10)
        normal = compute_notification_salience(gs, visitor_present=False)
        suppressed = compute_notification_salience(gs, visitor_present=True)
        assert suppressed < normal
        assert abs(suppressed - 0.10 * 0.3) < 0.01

    def test_topic_match_boosts(self):
        """Notification matching conversation topic gets boosted."""
        gs = _make_gap_score(curiosity_delta=0.10)
        boosted = compute_notification_salience(
            gs, visitor_present=True, conversation_topic_match=True)
        suppressed = compute_notification_salience(
            gs, visitor_present=True, conversation_topic_match=False)
        assert boosted > suppressed
        # Topic match with visitor: 0.10 * 1.5 = 0.15
        assert abs(boosted - 0.15) < 0.01

    def test_low_energy_suppresses(self):
        """Tired = notices less."""
        gs = _make_gap_score(curiosity_delta=0.10)
        normal = compute_notification_salience(gs, energy=0.5)
        tired = compute_notification_salience(gs, energy=0.15)
        assert tired < normal
        # Low energy: 0.10 * 0.2 = 0.02, below threshold (0.03) → filtered to 0.0
        assert tired == 0.0

    def test_below_threshold_filtered(self):
        """Gap score below threshold not included in cortex prompt."""
        gs = _make_gap_score(curiosity_delta=0.01)
        salience = compute_notification_salience(gs)
        # 0.01 is below the 0.03 threshold
        assert salience == 0.0

    def test_foreign_returns_zero(self):
        """Foreign content (delta=0) produces zero salience."""
        gs = _make_gap_score(curiosity_delta=0.0, gap_type='foreign')
        salience = compute_notification_salience(gs)
        assert salience == 0.0

    def test_high_curiosity_amplifies(self):
        """High diversive curiosity amplifies notification salience."""
        gs = _make_gap_score(curiosity_delta=0.10)
        normal = compute_notification_salience(gs, diversive_curiosity=0.4)
        amplified = compute_notification_salience(gs, diversive_curiosity=0.7)
        assert amplified > normal
        # High curiosity: 0.10 * 1.3 = 0.13
        assert abs(amplified - 0.13) < 0.01

    def test_salience_capped_at_one(self):
        """Salience never exceeds 1.0."""
        gs = _make_gap_score(curiosity_delta=0.15)
        salience = compute_notification_salience(
            gs, visitor_present=True, conversation_topic_match=True,
            diversive_curiosity=0.8)
        assert salience <= 1.0
