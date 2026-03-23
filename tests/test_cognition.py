"""Tests for alive_cognition — thalamus v2, channels, habituation, overrides."""

from __future__ import annotations

import pytest

from alive_cognition.channels import (
    ChannelContext,
    score_impact,
    score_relevance,
    score_surprise,
    score_urgency,
)
from alive_cognition.habituation import HabituationBuffer
from alive_cognition.overrides import check_overrides
from alive_cognition.thalamus import Thalamus
from alive_cognition.types import (
    ChannelScores,
    ChannelWeights,
    EventSchema,
    SalienceBand,
    ScoredPerception,
)
from alive_memory.types import EventType, Perception

# ── Helpers ──────────────────────────────────────────────────────────────


def _event(
    content: str,
    *,
    event_type: EventType = EventType.CONVERSATION,
    source: str = "chat",
    actor: str = "user",
    metadata: dict | None = None,
) -> EventSchema:
    return EventSchema(
        event_type=event_type,
        content=content,
        source=source,
        actor=actor,
        metadata=metadata or {},
    )


def _ctx(**kwargs) -> ChannelContext:
    return ChannelContext(**kwargs)


# =========================================================================
# 1. Types
# =========================================================================


def test_event_schema_defaults() -> None:
    e = EventSchema(event_type=EventType.CONVERSATION, content="hello")
    assert e.source == "chat"
    assert e.actor == "user"
    assert e.timestamp is not None
    assert e.metadata == {}


def test_event_schema_all_fields() -> None:
    from datetime import UTC, datetime

    ts = datetime(2025, 6, 1, tzinfo=UTC)
    e = EventSchema(
        event_type=EventType.ACTION,
        content="do something",
        source="tool",
        actor="agent",
        timestamp=ts,
        metadata={"key": "val"},
    )
    assert e.event_type == EventType.ACTION
    assert e.content == "do something"
    assert e.source == "tool"
    assert e.actor == "agent"
    assert e.timestamp == ts
    assert e.metadata == {"key": "val"}


def test_channel_scores_defaults_to_zeros() -> None:
    cs = ChannelScores()
    assert cs.relevance == 0.0
    assert cs.surprise == 0.0
    assert cs.impact == 0.0
    assert cs.urgency == 0.0


def test_salience_band_values() -> None:
    assert SalienceBand.DROP.value == 0
    assert SalienceBand.STORE.value == 1
    assert SalienceBand.PRIORITIZE.value == 2


def test_channel_weights_defaults() -> None:
    w = ChannelWeights()
    assert w.relevance == 0.35
    assert w.surprise == 0.25
    assert w.impact == 0.20
    assert w.urgency == 0.20


def test_scored_perception_to_perception_bridge() -> None:
    e = _event("What time is it?")
    sp = ScoredPerception(
        event=e,
        channels=ChannelScores(relevance=0.8),
        salience=0.72,
        band=SalienceBand.PRIORITIZE,
        reasons=["direct question"],
        novelty_factor=1.0,
    )
    p = sp.to_perception()
    assert isinstance(p, Perception)
    assert p.event_type == EventType.CONVERSATION
    assert p.content == "What time is it?"
    assert p.salience == 0.72
    assert p.timestamp == sp.timestamp
    assert p.metadata == e.metadata


# =========================================================================
# 2. Channels — score_relevance
# =========================================================================


def test_relevance_user_question_scores_higher() -> None:
    q = _event("What is your name?")
    s = _event("The sky is blue.")
    ctx = _ctx()
    q_score, _ = score_relevance(q, ctx)
    s_score, _ = score_relevance(s, ctx)
    assert q_score > s_score


def test_relevance_active_goals_boost() -> None:
    e = _event("We need to finish the pottery order.")
    ctx_no_goals = _ctx()
    ctx_goals = _ctx(active_goals=["pottery order"])
    score_no, _ = score_relevance(e, ctx_no_goals)
    score_yes, _ = score_relevance(e, ctx_goals)
    assert score_yes > score_no


def test_relevance_identity_keywords_boost() -> None:
    e = _event("The shopkeeper greeted the visitor.")
    ctx_no = _ctx()
    ctx_kw = _ctx(identity_keywords=["shopkeeper"])
    score_no, _ = score_relevance(e, ctx_no)
    score_kw, _ = score_relevance(e, ctx_kw)
    assert score_kw > score_no


def test_relevance_returns_reasons() -> None:
    e = _event("What do you sell?")
    ctx = _ctx(identity_keywords=["sell"])
    _, reasons = score_relevance(e, ctx)
    assert isinstance(reasons, list)
    assert len(reasons) > 0
    assert all(isinstance(r, str) for r in reasons)


# =========================================================================
# 2. Channels — score_surprise
# =========================================================================


def test_surprise_high_density_scores_higher() -> None:
    dense = _event(
        "Quantum entanglement enables instantaneous photon correlation measurements "
        "across astronomical distances using Bell inequality violations."
    )
    filler = _event(
        "I was just going to go out and see if we could also get some of "
        "the things that were there and also some more stuff."
    )
    ctx = _ctx()
    dense_score, _ = score_surprise(dense, ctx)
    filler_score, _ = score_surprise(filler, ctx)
    assert dense_score > filler_score


def test_surprise_short_content_low_baseline() -> None:
    e = _event("ok")
    ctx = _ctx()
    score, reasons = score_surprise(e, ctx)
    assert score == pytest.approx(0.05)
    assert "short content" in reasons[0].lower()


def test_surprise_preference_revelation_boost() -> None:
    pref = _event("I always prefer dark roast coffee in the morning.")
    plain = _event("Coffee is a popular beverage consumed worldwide daily.")
    ctx = _ctx()
    pref_score, pref_reasons = score_surprise(pref, ctx)
    plain_score, _ = score_surprise(plain, ctx)
    assert pref_score > plain_score
    assert any("preference" in r.lower() for r in pref_reasons)


# =========================================================================
# 2. Channels — score_impact
# =========================================================================


def test_impact_negative_affect_scores_higher() -> None:
    neg = _event("I am frustrated and angry about this.")
    neutral = _event("The meeting is scheduled for Tuesday.")
    ctx = _ctx()
    neg_score, _ = score_impact(neg, ctx)
    neu_score, _ = score_impact(neutral, ctx)
    assert neg_score > neu_score


def test_impact_safety_risk_produces_high_score() -> None:
    risky = _event("There is a security breach and the password was leaked.")
    ctx = _ctx()
    score, reasons = score_impact(risky, ctx)
    assert score >= 0.4
    assert any("risk" in r.lower() or "safety" in r.lower() for r in reasons)


def test_impact_intensity_markers_increase_score() -> None:
    intense = _event("I am extremely angry about this terrible situation.")
    mild = _event("I am angry about this situation.")
    ctx = _ctx()
    intense_score, intense_reasons = score_impact(intense, ctx)
    mild_score, _ = score_impact(mild, ctx)
    assert intense_score > mild_score
    assert any("intensity" in r.lower() for r in intense_reasons)


# =========================================================================
# 2. Channels — score_urgency
# =========================================================================


@pytest.mark.parametrize("keyword", ["urgent", "now", "asap"])
def test_urgency_time_pressure_keywords(keyword: str) -> None:
    urgent = _event(f"I need this done {keyword}.")
    casual = _event("Whenever you get a chance, no rush.")
    ctx = _ctx()
    urg_score, _ = score_urgency(urgent, ctx)
    cas_score, _ = score_urgency(casual, ctx)
    assert urg_score > cas_score


@pytest.mark.parametrize("indicator", ["failed", "crash", "error"])
def test_urgency_error_indicators(indicator: str) -> None:
    error_event = _event(f"The system {indicator} during deployment.")
    normal = _event("The system ran the deployment successfully.")
    ctx = _ctx()
    err_score, err_reasons = score_urgency(error_event, ctx)
    nor_score, _ = score_urgency(normal, ctx)
    assert err_score > nor_score
    assert any("error" in r.lower() for r in err_reasons)


def test_urgency_user_question_implicit() -> None:
    q = _event("Why is the server down?")
    ctx = _ctx()
    score, reasons = score_urgency(q, ctx)
    assert any("user question" in r.lower() for r in reasons)


# =========================================================================
# 3. Habituation
# =========================================================================


def test_habituation_first_event_novelty_is_one() -> None:
    buf = HabituationBuffer()
    e = _event("Hello, how are you?")
    assert buf.novelty_factor(e) == 1.0


def test_habituation_repeated_event_decays() -> None:
    buf = HabituationBuffer(decay_rate=0.85)
    e = _event("Hello, how are you?")
    buf.record(e)
    nf = buf.novelty_factor(e)
    assert nf < 1.0
    assert nf == pytest.approx(0.85, abs=0.01)


def test_habituation_novelty_floors_at_minimum() -> None:
    buf = HabituationBuffer(decay_rate=0.5)
    e = _event("repeat this")
    # Record many identical events
    for _ in range(20):
        buf.record(e)
    nf = buf.novelty_factor(e)
    assert nf == pytest.approx(0.4, abs=0.01)


def test_habituation_different_events_no_decay() -> None:
    buf = HabituationBuffer()
    e1 = _event("First unique message with lots of words to differ")
    e2 = _event("Completely different second message about other things entirely")
    buf.record(e1)
    nf = buf.novelty_factor(e2)
    assert nf == 1.0


def test_habituation_clear_resets() -> None:
    buf = HabituationBuffer()
    e = _event("same same same")
    buf.record(e)
    assert buf.novelty_factor(e) < 1.0
    buf.clear()
    assert buf.novelty_factor(e) == 1.0


def test_habituation_buffer_respects_max_size() -> None:
    buf = HabituationBuffer(max_size=3)
    for i in range(5):
        buf.record(_event(f"unique message number {i}", source="sensor", actor="environment"))
    # Internal buffer should be capped at max_size
    assert len(buf._buffer) == 3


# =========================================================================
# 4. Overrides
# =========================================================================


def test_override_user_question_forces_prioritize() -> None:
    e = _event("What is the status?")
    result = check_overrides(e)
    assert result.applied is True
    assert result.force_band == SalienceBand.PRIORITIZE
    assert "question" in result.reason.lower()


@pytest.mark.parametrize("keyword", ["emergency", "danger", "security breach"])
def test_override_safety_keywords_force_prioritize(keyword: str) -> None:
    e = _event(f"There is a {keyword} happening right now.", actor="agent")
    result = check_overrides(e)
    assert result.applied is True
    assert result.force_band == SalienceBand.PRIORITIZE


def test_override_metadata_salience_high_forces_prioritize() -> None:
    e = _event("normal content", actor="agent", metadata={"salience": 0.9})
    result = check_overrides(e)
    assert result.applied is True
    assert result.force_band == SalienceBand.PRIORITIZE


def test_override_heartbeat_forces_drop() -> None:
    e = _event(
        "heartbeat",
        event_type=EventType.SYSTEM,
        actor="environment",
    )
    result = check_overrides(e)
    assert result.applied is True
    assert result.force_band == SalienceBand.DROP


def test_override_spam_forces_drop() -> None:
    e = _event("buy cheap stuff now", metadata={"spam": True})
    result = check_overrides(e)
    assert result.applied is True
    assert result.force_band == SalienceBand.DROP


def test_override_normal_event_not_applied() -> None:
    e = _event("The weather is nice today.", actor="agent")
    result = check_overrides(e)
    assert result.applied is False
    assert result.force_band is None


# =========================================================================
# 5. Thalamus (integration)
# =========================================================================


def test_thalamus_perceive_returns_scored_perception() -> None:
    t = Thalamus()
    e = _event("Tell me about your day.")
    sp = t.perceive(e)
    assert isinstance(sp, ScoredPerception)
    assert isinstance(sp.channels, ChannelScores)
    assert isinstance(sp.band, SalienceBand)


def test_thalamus_salience_in_range() -> None:
    t = Thalamus()
    e = _event("Some arbitrary content for testing.")
    sp = t.perceive(e)
    assert 0.0 <= sp.salience <= 1.0


def test_thalamus_band_drop_for_low_salience() -> None:
    """System event with bland content should score low -> DROP band."""
    t = Thalamus()
    e = _event("ok", event_type=EventType.SYSTEM, actor="environment")
    sp = t.perceive(e)
    # "ok" from system/environment: no user boost, no question, minimal content
    assert sp.band == SalienceBand.DROP


def test_thalamus_band_prioritize_for_user_question() -> None:
    t = Thalamus()
    e = _event("What is your favorite color?")
    sp = t.perceive(e)
    assert sp.band == SalienceBand.PRIORITIZE


def test_thalamus_repeated_events_decay() -> None:
    t = Thalamus()
    e = _event("Hello there friend")
    sp1 = t.perceive(e)
    sp2 = t.perceive(e)
    # The second perception of the same event should have lower novelty
    assert sp2.novelty_factor < sp1.novelty_factor


def test_thalamus_reset_habituation() -> None:
    t = Thalamus()
    e = _event("Repeating message for habituation")
    t.perceive(e)
    t.perceive(e)
    t.reset_habituation()
    sp = t.perceive(e)
    assert sp.novelty_factor == 1.0


def test_thalamus_update_context_changes_scoring() -> None:
    t = Thalamus()
    e = _event("We should work on the pottery inventory.")
    sp_before = t.perceive(e)
    t.reset_habituation()  # clear habituation so repeat doesn't decay

    t.update_context(active_goals=["pottery inventory"])
    sp_after = t.perceive(e)
    assert sp_after.channels.relevance > sp_before.channels.relevance


def test_thalamus_metadata_salience_override() -> None:
    t = Thalamus()
    e = _event("anything", actor="agent", metadata={"salience": 0.55})
    sp = t.perceive(e)
    assert sp.salience == pytest.approx(0.55)


def test_thalamus_reasons_non_empty() -> None:
    t = Thalamus()
    e = _event("What should we do about the broken pipe?")
    sp = t.perceive(e)
    assert len(sp.reasons) > 0


def test_thalamus_to_perception_bridge() -> None:
    t = Thalamus()
    e = _event("Hello from the thalamus.")
    sp = t.perceive(e)
    p = sp.to_perception()
    assert isinstance(p, Perception)
    assert p.content == "Hello from the thalamus."
    assert p.salience == sp.salience


# =========================================================================
# 6. Backward compatibility
# =========================================================================


def test_backward_compat_affect_import() -> None:
    """Old import path still resolves a working callable."""
    from alive_memory.intake.affect import apply_affect  # noqa: F811

    assert callable(apply_affect)


def test_backward_compat_drift_import() -> None:
    """Old import path still resolves a working class."""
    from alive_memory.identity.drift import DriftDetector  # noqa: F811

    assert DriftDetector is not None
    assert hasattr(DriftDetector, "detect")


def test_backward_compat_meta_controller_import() -> None:
    """Old import path still resolves a working callable."""
    from alive_memory.meta.controller import classify_outcome  # noqa: F811

    assert callable(classify_outcome)


# =========================================================================
# 7. Band-to-action mapping
# =========================================================================


def test_band_drop_value() -> None:
    assert SalienceBand.DROP.value == 0


def test_band_store_value() -> None:
    assert SalienceBand.STORE.value == 1


def test_band_prioritize_value() -> None:
    assert SalienceBand.PRIORITIZE.value == 2
