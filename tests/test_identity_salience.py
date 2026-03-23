"""Tests for identity-aware salience (Phase 3).

Tests:
- Metadata salience override skips heuristic
- Identity keyword boost
- Raised day memory cap (500)
"""

from __future__ import annotations

from alive_cognition import Thalamus
from alive_cognition.types import EventSchema
from alive_memory.types import EventType


def test_metadata_salience_override() -> None:
    """metadata.salience should bypass all heuristic computation."""
    t = Thalamus()
    p = t.perceive(
        EventSchema(
            event_type=EventType.CONVERSATION,
            content="irrelevant content that would normally get some salience",
            metadata={"salience": 0.1},
        )
    )
    assert p.salience == 0.1


def test_metadata_salience_override_high() -> None:
    t = Thalamus()
    p = t.perceive(
        EventSchema(
            event_type=EventType.SYSTEM,
            content="system event",
            metadata={"salience": 0.95},
        )
    )
    assert p.salience == 0.95


def test_identity_boost_increases_salience() -> None:
    """Events matching identity keywords should get a salience boost."""
    # Without identity keywords
    t_base = Thalamus()
    p_base = t_base.perceive(
        EventSchema(
            event_type=EventType.CONVERSATION,
            content="A customer asked about rare pottery",
        )
    )

    # With identity keywords matching content
    t_boosted = Thalamus(identity_keywords=["customer", "pottery", "shopkeeper"])
    p_boosted = t_boosted.perceive(
        EventSchema(
            event_type=EventType.CONVERSATION,
            content="A customer asked about rare pottery",
        )
    )

    assert p_boosted.salience > p_base.salience


def test_identity_boost_no_match() -> None:
    """Non-matching identity keywords should not change salience."""
    t_base = Thalamus()
    p_base = t_base.perceive(
        EventSchema(
            event_type=EventType.CONVERSATION,
            content="The weather is nice today",
        )
    )

    t_kw = Thalamus(identity_keywords=["customer", "pottery"])
    p_same = t_kw.perceive(
        EventSchema(
            event_type=EventType.CONVERSATION,
            content="The weather is nice today",
        )
    )

    assert p_same.salience == p_base.salience


def test_identity_boost_via_update_context() -> None:
    """Identity boost via update_context should also work."""
    t = Thalamus()
    event = EventSchema(
        event_type=EventType.CONVERSATION,
        content="A customer walked in",
    )
    p_no_boost = t.perceive(event)

    t.reset_habituation()  # clear habituation from first perceive
    t.update_context(identity_keywords=["customer"])
    p_boosted = t.perceive(event)

    assert p_boosted.salience >= p_no_boost.salience


def test_day_memory_cap_raised() -> None:
    """MAX_DAY_MOMENTS should be 500, not 30."""
    from alive_memory.intake.formation import MAX_DAY_MOMENTS

    assert MAX_DAY_MOMENTS == 500
