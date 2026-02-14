"""Tests for inhibition system — Phase 3.

Covers: signal detection, inhibition formation/strengthening/weakening,
Gate 6 in basal ganglia, and inhibition deletion.
"""

import json
import pytest
from unittest.mock import AsyncMock, patch

from models.pipeline import (
    Intention, ValidatedOutput, ActionDecision, MotorPlan,
    ActionResult, BodyOutput, InhibitionCheck,
)
from models.state import DrivesState
from pipeline.output import (
    _detect_negative_signal, _detect_positive_signal,
    _maybe_form_inhibition,
)
from pipeline.basal_ganglia import (
    select_actions, _check_inhibition, _matches_pattern,
)


# ── Fixtures ──

@pytest.fixture
def drives():
    return DrivesState(energy=0.8, social_hunger=0.5)


@pytest.fixture
def context_with_visitor():
    return {'visitor_present': True, 'turn_count': 5, 'mode': 'engage'}


def _make_decision(action='speak', target='visitor', impulse=0.8):
    return ActionDecision(
        action=action, content='hello', target=target,
        impulse=impulse, priority=0.8, status='approved',
        source='cortex',
    )


def _make_action_result(action='speak', success=True):
    return ActionResult(action=action, success=success)


def _validated_with_intentions(intentions):
    v = ValidatedOutput(dialogue='...', internal_monologue='Thinking.', expression='neutral')
    v.intentions = intentions
    v.approved_actions = []
    v.actions = []
    return v


# ── Signal Detection Tests ──

class TestNegativeSignalDetection:
    """Internal feeling patterns trigger negative signals."""

    def test_regret_detected(self):
        assert _detect_negative_signal("I regret saying that") is True

    def test_shouldnt_have_detected(self):
        assert _detect_negative_signal("I shouldn't have been so direct") is True

    def test_felt_wrong_detected(self):
        assert _detect_negative_signal("That felt wrong somehow") is True

    def test_pushed_too_hard_detected(self):
        assert _detect_negative_signal("I pushed too hard there") is True

    def test_neutral_feelings_no_signal(self):
        assert _detect_negative_signal("A quiet moment, nothing special") is False

    def test_empty_feelings_no_signal(self):
        assert _detect_negative_signal("") is False


class TestPositiveSignalDetection:
    """Positive outcomes weaken inhibitions."""

    def test_journal_write_positive(self):
        result = _make_action_result(action='write_journal', success=True)
        assert _detect_positive_signal(result) is True

    def test_failed_journal_not_positive(self):
        result = _make_action_result(action='write_journal', success=False)
        assert _detect_positive_signal(result) is False

    def test_speak_not_positive_alone(self):
        result = _make_action_result(action='speak', success=True)
        assert _detect_positive_signal(result) is False


# ── Pattern Matching Tests ──

class TestPatternMatching:
    """Coarse-grained context matching for inhibitions."""

    def test_matching_pattern(self):
        pattern = json.dumps({'mode': 'engage', 'visitor_present': True})
        context = {'mode': 'engage', 'visitor_present': True, 'turn_count': 5}
        assert _matches_pattern(pattern, context) is True

    def test_non_matching_pattern(self):
        pattern = json.dumps({'mode': 'idle', 'visitor_present': False})
        context = {'mode': 'engage', 'visitor_present': True}
        assert _matches_pattern(pattern, context) is False

    def test_partial_match_missing_key(self):
        pattern = json.dumps({'mode': 'engage', 'extra_key': True})
        context = {'mode': 'engage'}
        assert _matches_pattern(pattern, context) is True

    def test_malformed_pattern_matches_conservatively(self):
        assert _matches_pattern('not json', {}) is True

    def test_empty_pattern_matches_all(self):
        pattern = json.dumps({})
        assert _matches_pattern(pattern, {'mode': 'engage'}) is True


# ── Inhibition Formation Tests ──

class TestInhibitionFormation:
    """Inhibitions form on negative signals and weaken on positive."""

    @pytest.mark.asyncio
    async def test_new_inhibition_forms_on_negative(self):
        decision = _make_decision()
        with patch('pipeline.output.db') as mock_db:
            mock_db.find_matching_inhibition = AsyncMock(return_value=None)
            mock_db.create_inhibition = AsyncMock(return_value='inh_001')

            await _maybe_form_inhibition(decision, negative=True, positive=False)

            mock_db.create_inhibition.assert_called_once()
            call_kwargs = mock_db.create_inhibition.call_args
            assert call_kwargs.kwargs['strength'] == 0.3
            assert call_kwargs.kwargs['action'] == 'speak'

    @pytest.mark.asyncio
    async def test_existing_inhibition_strengthens(self):
        decision = _make_decision()
        existing = {
            'id': 'inh_001', 'action': 'speak',
            'strength': 0.3, 'trigger_count': 1,
            'pattern': '{}', 'reason': '{}',
        }
        with patch('pipeline.output.db') as mock_db:
            mock_db.find_matching_inhibition = AsyncMock(return_value=existing)
            mock_db.update_inhibition = AsyncMock()

            await _maybe_form_inhibition(decision, negative=True, positive=False)

            mock_db.update_inhibition.assert_called_once()
            call_kwargs = mock_db.update_inhibition.call_args
            assert abs(call_kwargs.kwargs['strength'] - 0.45) < 1e-9  # 0.3 + 0.15

    @pytest.mark.asyncio
    async def test_inhibition_strength_capped_at_1(self):
        decision = _make_decision()
        existing = {
            'id': 'inh_001', 'action': 'speak',
            'strength': 0.95, 'trigger_count': 5,
            'pattern': '{}', 'reason': '{}',
        }
        with patch('pipeline.output.db') as mock_db:
            mock_db.find_matching_inhibition = AsyncMock(return_value=existing)
            mock_db.update_inhibition = AsyncMock()

            await _maybe_form_inhibition(decision, negative=True, positive=False)

            call_kwargs = mock_db.update_inhibition.call_args
            assert call_kwargs.kwargs['strength'] == 1.0  # capped

    @pytest.mark.asyncio
    async def test_positive_signal_weakens_inhibition(self):
        decision = _make_decision()
        existing = {
            'id': 'inh_001', 'action': 'speak',
            'strength': 0.5, 'trigger_count': 3,
            'pattern': '{}', 'reason': '{}',
        }
        with patch('pipeline.output.db') as mock_db:
            mock_db.find_matching_inhibition = AsyncMock(return_value=existing)
            mock_db.update_inhibition = AsyncMock()

            await _maybe_form_inhibition(decision, negative=False, positive=True)

            call_kwargs = mock_db.update_inhibition.call_args
            assert call_kwargs.kwargs['strength'] == 0.4  # 0.5 - 0.1

    @pytest.mark.asyncio
    async def test_weak_inhibition_deleted(self):
        decision = _make_decision()
        existing = {
            'id': 'inh_001', 'action': 'speak',
            'strength': 0.04, 'trigger_count': 1,
            'pattern': '{}', 'reason': '{}',
        }
        with patch('pipeline.output.db') as mock_db:
            mock_db.find_matching_inhibition = AsyncMock(return_value=existing)
            mock_db.delete_inhibition = AsyncMock()

            await _maybe_form_inhibition(decision, negative=False, positive=True)

            mock_db.delete_inhibition.assert_called_once_with('inh_001')

    @pytest.mark.asyncio
    async def test_no_signal_no_change(self):
        decision = _make_decision()
        with patch('pipeline.output.db') as mock_db:
            mock_db.find_matching_inhibition = AsyncMock()
            mock_db.create_inhibition = AsyncMock()
            mock_db.update_inhibition = AsyncMock()

            await _maybe_form_inhibition(decision, negative=False, positive=False)

            mock_db.create_inhibition.assert_not_called()
            mock_db.update_inhibition.assert_not_called()


# ── Gate 6 Tests ──

class TestGate6Inhibition:
    """Gate 6 in basal ganglia checks learned inhibitions."""

    @pytest.mark.asyncio
    async def test_strong_inhibition_suppresses(self):
        """An action with a strong inhibition gets blocked."""
        inhib = {
            'id': 'inh_001', 'action': 'speak',
            'pattern': json.dumps({'mode': 'engage'}),
            'reason': json.dumps({'action': 'speak', 'trigger': 'self_assessment'}),
            'strength': 0.9, 'trigger_count': 3,
            'formed_at': '2026-01-01', 'last_triggered': None,
        }
        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.basal_ganglia.random') as mock_random:
            mock_db.get_inhibitions_for_action = AsyncMock(return_value=[inhib])
            mock_db.update_inhibition = AsyncMock()
            mock_random.random.return_value = 0.5  # < 0.9 → suppresses

            result = await _check_inhibition('speak', {'mode': 'engage'})

            assert result.suppress is True
            assert result.inhibition_id == 'inh_001'

    @pytest.mark.asyncio
    async def test_weak_inhibition_ignored(self):
        """Inhibitions with strength < 0.2 are too weak to matter."""
        inhib = {
            'id': 'inh_001', 'action': 'speak',
            'pattern': json.dumps({}),
            'reason': '{}',
            'strength': 0.15, 'trigger_count': 1,
            'formed_at': '2026-01-01', 'last_triggered': None,
        }
        with patch('pipeline.basal_ganglia.db') as mock_db:
            mock_db.get_inhibitions_for_action = AsyncMock(return_value=[inhib])

            result = await _check_inhibition('speak', {})

            assert result.suppress is False

    @pytest.mark.asyncio
    async def test_no_inhibitions_passes(self):
        """No inhibitions → action passes Gate 6."""
        with patch('pipeline.basal_ganglia.db') as mock_db:
            mock_db.get_inhibitions_for_action = AsyncMock(return_value=[])

            result = await _check_inhibition('speak', {})

            assert result.suppress is False

    @pytest.mark.asyncio
    async def test_probabilistic_pass(self):
        """Even strong inhibitions sometimes let actions through."""
        inhib = {
            'id': 'inh_001', 'action': 'speak',
            'pattern': json.dumps({}),
            'reason': '{}',
            'strength': 0.3, 'trigger_count': 1,
            'formed_at': '2026-01-01', 'last_triggered': None,
        }
        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.basal_ganglia.random') as mock_random:
            mock_db.get_inhibitions_for_action = AsyncMock(return_value=[inhib])
            mock_random.random.return_value = 0.5  # > 0.3 → passes

            result = await _check_inhibition('speak', {})

            assert result.suppress is False

    @pytest.mark.asyncio
    async def test_inhibited_action_in_motor_plan(self, drives):
        """Inhibited action appears in motor_plan.suppressed with 'inhibited' status."""
        inhib = {
            'id': 'inh_001', 'action': 'speak',
            'pattern': json.dumps({}),
            'reason': json.dumps({'action': 'speak', 'trigger': 'self_assessment'}),
            'strength': 0.9, 'trigger_count': 3,
            'formed_at': '2026-01-01', 'last_triggered': None,
        }
        intentions = [Intention(action='speak', target='visitor', content='hi', impulse=0.8)]
        validated = _validated_with_intentions(intentions)

        with patch('pipeline.basal_ganglia.db') as mock_db, \
             patch('pipeline.basal_ganglia.random') as mock_random:
            mock_db.get_inhibitions_for_action = AsyncMock(return_value=[inhib])
            mock_db.update_inhibition = AsyncMock()
            mock_random.random.return_value = 0.1  # < 0.9 → suppresses

            plan = await select_actions(validated, drives, context={'mode': 'engage', 'visitor_present': True})

            # Find the inhibited action specifically (other suppressed may exist)
            inhibited = [s for s in plan.suppressed if s.status == 'inhibited']
            assert len(inhibited) == 1
            assert inhibited[0].status == 'inhibited'
            assert 'Learned:' in inhibited[0].suppression_reason

    @pytest.mark.asyncio
    async def test_db_error_graceful_degradation(self):
        """DB errors during inhibition check don't crash the pipeline."""
        with patch('pipeline.basal_ganglia.db') as mock_db:
            mock_db.get_inhibitions_for_action = AsyncMock(
                side_effect=Exception("DB error")
            )

            result = await _check_inhibition('speak', {})

            assert result.suppress is False
