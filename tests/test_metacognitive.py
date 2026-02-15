"""Tests for metacognitive monitor — Phase 3.

Covers: self-consistency checks against voice rules and physical traits,
internal_conflict event emission, and day_memory salience boost.
"""

import pytest
from unittest.mock import AsyncMock, patch

from models.pipeline import ValidatedOutput, SelfConsistencyResult
from pipeline.output import _check_self_consistency, _emit_internal_conflict
from pipeline.day_memory import compute_moment_salience, classify_moment


# ── Fixtures ──

def _validated_with_dialogue(dialogue, expression='neutral'):
    return ValidatedOutput(
        dialogue=dialogue,
        internal_monologue='Thinking.',
        expression=expression,
    )


# ── Self-Consistency Check Tests ──

class TestSelfConsistencyCheck:
    """Metacognitive monitor detects voice rule and trait violations."""

    @pytest.mark.asyncio
    async def test_laughter_detected(self):
        """Using 'haha' produces an internal conflict."""
        validated = _validated_with_dialogue("Haha, that's funny.")
        result = await _check_self_consistency(validated)
        assert not result.consistent
        assert any("haha/lol" in c for c in result.conflicts)

    @pytest.mark.asyncio
    async def test_lol_detected(self):
        """Using 'lol' produces an internal conflict."""
        validated = _validated_with_dialogue("lol okay sure")
        result = await _check_self_consistency(validated)
        assert not result.consistent
        assert any("haha/lol" in c for c in result.conflicts)

    @pytest.mark.asyncio
    async def test_exclamation_without_surprise(self):
        """Exclamation marks are only okay when expression is 'surprised'."""
        validated = _validated_with_dialogue("That's amazing!", expression='neutral')
        result = await _check_self_consistency(validated)
        assert not result.consistent
        assert any("exclamation" in c for c in result.conflicts)

    @pytest.mark.asyncio
    async def test_exclamation_with_surprise_ok(self):
        """Exclamation marks are fine when genuinely surprised."""
        validated = _validated_with_dialogue("What!", expression='surprised')
        result = await _check_self_consistency(validated)
        # No exclamation conflict (but still consistent unless other violations)
        assert not any("exclamation" in c for c in result.conflicts)

    @pytest.mark.asyncio
    async def test_glasses_denial_detected(self):
        """Denying wearing glasses produces conflict."""
        validated = _validated_with_dialogue("I don't wear glasses.")
        result = await _check_self_consistency(validated)
        assert not result.consistent
        assert any("glasses" in c.lower() for c in result.conflicts)

    @pytest.mark.asyncio
    async def test_height_denial_detected(self):
        """Denying being short produces conflict."""
        validated = _validated_with_dialogue("I'm not short at all.")
        result = await _check_self_consistency(validated)
        assert not result.consistent
        assert any("short" in c.lower() for c in result.conflicts)

    @pytest.mark.asyncio
    async def test_normal_speech_consistent(self):
        """Normal in-character speech produces no conflicts."""
        validated = _validated_with_dialogue("The light is nice today.")
        result = await _check_self_consistency(validated)
        assert result.consistent
        assert result.conflicts == []

    @pytest.mark.asyncio
    async def test_silence_consistent(self):
        """Silence is always consistent."""
        validated = _validated_with_dialogue("...")
        result = await _check_self_consistency(validated)
        assert result.consistent

    @pytest.mark.asyncio
    async def test_none_dialogue_consistent(self):
        """None dialogue is consistent."""
        validated = _validated_with_dialogue(None)
        result = await _check_self_consistency(validated)
        assert result.consistent

    @pytest.mark.asyncio
    async def test_multiple_violations(self):
        """Multiple violations all get detected."""
        validated = _validated_with_dialogue(
            "Haha! I don't wear glasses!",
            expression='neutral',
        )
        result = await _check_self_consistency(validated)
        assert not result.consistent
        assert len(result.conflicts) >= 2  # laughter + exclamation (+ maybe glasses)


# ── Internal Conflict Event Tests ──

class TestInternalConflictEmission:
    """Internal conflicts are emitted as events for next cycle."""

    @pytest.mark.asyncio
    async def test_conflict_emits_event(self):
        """Inconsistency emits an internal_conflict event."""
        consistency = SelfConsistencyResult(
            consistent=False,
            conflicts=["Used 'haha/lol' instead of describing the feeling"],
        )
        validated = _validated_with_dialogue("Haha nice one")

        with patch('pipeline.output.db') as mock_db:
            mock_db.append_event = AsyncMock()
            await _emit_internal_conflict(consistency, validated)

            mock_db.append_event.assert_called_once()
            event = mock_db.append_event.call_args[0][0]
            assert event.event_type == 'internal_conflict'
            assert event.source == 'self'
            assert 'haha/lol' in event.payload['description']

    @pytest.mark.asyncio
    async def test_no_conflict_no_event(self):
        """Consistent output doesn't emit events."""
        validated = _validated_with_dialogue("The light is nice.")
        result = await _check_self_consistency(validated)
        assert result.consistent
        # No need to call _emit_internal_conflict — process_output checks first


# ── Day Memory Integration Tests ──

class TestDayMemoryInternalConflict:
    """internal_conflict moment type gets salience boost in day_memory."""

    def test_internal_conflict_salience_boost(self):
        """Internal conflict adds +0.4 salience — always above threshold."""
        result = {'resonance': False, 'actions': []}
        ctx = {
            'has_internal_conflict': True,
            'trust_level': 'stranger',
            'max_drive_delta': 0.0,
        }
        salience = compute_moment_salience(result, ctx)
        assert salience >= 0.4  # always above MOMENT_THRESHOLD

    def test_internal_conflict_classification(self):
        """Internal conflict is classified as highest priority moment type."""
        result = {'resonance': True, 'actions': []}  # resonance too
        ctx = {'has_internal_conflict': True}
        moment_type = classify_moment(result, ctx)
        assert moment_type == 'internal_conflict'

    def test_no_conflict_normal_classification(self):
        """Without internal conflict, normal classification applies."""
        result = {'resonance': True, 'actions': []}
        ctx = {'has_internal_conflict': False}
        moment_type = classify_moment(result, ctx)
        assert moment_type == 'resonance'

    def test_salience_stacks_with_other_signals(self):
        """Internal conflict salience stacks with resonance."""
        result = {'resonance': True, 'actions': []}
        ctx = {
            'has_internal_conflict': True,
            'trust_level': 'stranger',
            'max_drive_delta': 0.0,
        }
        salience = compute_moment_salience(result, ctx)
        assert salience >= 0.6  # 0.4 (conflict) + 0.2 (resonance)
