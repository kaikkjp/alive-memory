"""Tests for TASK-044: Reflection loop + resolution rewards.

Verifies: memory creation, EC resolution, mood rewards, boring content
effects, no curiosity drain on read, and consumption tracking.
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.pipeline import ValidatedOutput, BodyOutput, ActionResult
from models.state import DrivesState, EpistemicCuriosity, EPISTEMIC_CONFIG
from pipeline.output import (
    process_reflection,
    _is_boring_reflection,
    _has_memory_signal,
    _has_resolution_signal,
    ACTION_DRIVE_EFFECTS,
)


def _make_body_output(read_results=None):
    """Build a BodyOutput with optional read_content results."""
    bo = BodyOutput()
    if read_results:
        for r in read_results:
            bo.executed.append(r)
    return bo


def _make_read_result(content_id='c1', title='Test Article', success=True):
    """Build an ActionResult for read_content."""
    return ActionResult(
        action='read_content',
        success=success,
        payload={
            'content_id': content_id,
            'title': title,
            'full_content': 'Some content...',
            'content_type': 'article',
            'source': 'rss',
        },
    )


def _make_validated(monologue='', dialogue=''):
    """Build a ValidatedOutput for reflection tests."""
    return ValidatedOutput(
        internal_monologue=monologue,
        dialogue=dialogue or '...',
        expression='neutral',
        body_state='sitting',
        gaze='forward',
    )


def _make_drives(**overrides):
    defaults = dict(
        social_hunger=0.5,
        curiosity=0.5,
        expression_need=0.3,
        rest_need=0.2,
        energy=0.7,
        mood_valence=0.0,
        mood_arousal=0.3,
    )
    defaults.update(overrides)
    return DrivesState(**defaults)


def _make_ec(topic='quantum computing', question='How do qubits work?'):
    return EpistemicCuriosity(
        id='ec-1',
        topic=topic,
        question=question,
        intensity=0.5,
        source_type='content',
        source_id='c0',
        created_at='2026-01-01T00:00:00Z',
        last_reinforced_at='2026-01-01T00:00:00Z',
    )


@pytest.fixture(autouse=True)
def _patch_db():
    """Patch db at the pipeline.output module level."""
    mock_db = MagicMock()
    mock_db.update_pool_item = AsyncMock()
    mock_db.get_drives_state = AsyncMock(return_value=_make_drives())
    mock_db.save_drives_state = AsyncMock()
    mock_db.insert_text_fragment = AsyncMock()
    mock_db.get_active_epistemic_curiosities = AsyncMock(return_value=[])
    mock_db.resolve_epistemic_curiosity = AsyncMock()
    with patch('pipeline.output.db', mock_db):
        yield mock_db


class TestReflectionDetectors:
    """Pattern detectors for boring, memory, and resolution signals."""

    def test_boring_empty_monologue(self):
        assert _is_boring_reflection('') is True

    def test_boring_nothing_interesting(self):
        assert _is_boring_reflection('Nothing interesting here.') is True

    def test_boring_already_knew(self):
        assert _is_boring_reflection('Already knew all of this.') is True

    def test_not_boring_genuine_reaction(self):
        assert _is_boring_reflection('This reminds me of what the visitor said about art') is False

    def test_memory_signal_learned(self):
        assert _has_memory_signal('I learned that photons have dual nature.') is True

    def test_memory_signal_connects(self):
        assert _has_memory_signal('This connects to what I read about astronomy last week.') is True

    def test_no_memory_signal_short(self):
        assert _has_memory_signal('ok') is False

    def test_resolution_signal(self):
        assert _has_resolution_signal('Now I understand why the tides work that way.') is True

    def test_resolution_answers(self):
        assert _has_resolution_signal("That's what causes auroras.") is True

    def test_no_resolution_signal(self):
        assert _has_resolution_signal('Interesting article about cats.') is False


class TestReflectionLoop:
    """process_reflection() effects."""

    @pytest.mark.asyncio
    async def test_no_read_no_effects(self, _patch_db):
        """No read_content in body output → no effects."""
        validated = _make_validated(monologue='Just thinking about things.')
        bo = _make_body_output()
        effects = await process_reflection(validated, bo)
        assert effects['boring'] is False
        assert effects['memory_created'] is False
        _patch_db.update_pool_item.assert_not_called()

    @pytest.mark.asyncio
    async def test_reflection_creates_memory(self, _patch_db):
        """Monologue with memory signal → memory_created effect."""
        validated = _make_validated(
            monologue='I learned something fascinating about deep sea creatures.'
        )
        bo = _make_body_output(read_results=[_make_read_result()])
        effects = await process_reflection(validated, bo)
        assert effects['memory_created'] is True
        _patch_db.insert_text_fragment.assert_called()

    @pytest.mark.asyncio
    async def test_reflection_resolves_ec(self, _patch_db):
        """Resolution signal + matching active EC → resolved, mood bump."""
        ec = _make_ec(topic='deep sea creatures', question='How deep can fish live?')
        _patch_db.get_active_epistemic_curiosities = AsyncMock(return_value=[ec])

        validated = _make_validated(
            monologue='Now I understand how deep sea creatures survive the pressure.'
        )
        bo = _make_body_output(read_results=[
            _make_read_result(title='Deep Sea Creatures'),
        ])
        effects = await process_reflection(validated, bo)
        assert effects['question_resolved'] is True
        _patch_db.resolve_epistemic_curiosity.assert_called_once()

    @pytest.mark.asyncio
    async def test_resolution_mood_reward(self, _patch_db):
        """EC resolution bumps mood_valence by EPISTEMIC_CONFIG value."""
        starting_drives = _make_drives(mood_valence=0.0)
        _patch_db.get_drives_state = AsyncMock(return_value=starting_drives)

        ec = _make_ec(topic='quantum computing', question='How do qubits work?')
        _patch_db.get_active_epistemic_curiosities = AsyncMock(return_value=[ec])

        validated = _make_validated(
            monologue="Now I understand how superposition works in quantum computing."
        )
        bo = _make_body_output(read_results=[
            _make_read_result(title='Quantum Computing Basics'),
        ])
        await process_reflection(validated, bo)

        # Check that save_drives_state was called with bumped mood
        calls = _patch_db.save_drives_state.call_args_list
        # At least one save should have mood bump
        found_mood_bump = False
        for call in calls:
            drives = call[0][0]
            if drives.mood_valence >= EPISTEMIC_CONFIG['resolution_mood_bump'] - 0.01:
                found_mood_bump = True
                break
        assert found_mood_bump, f"Expected mood bump of {EPISTEMIC_CONFIG['resolution_mood_bump']}"

    @pytest.mark.asyncio
    async def test_boring_content_effects(self, _patch_db):
        """Boring reflection → diversive drain + energy cost."""
        starting_drives = _make_drives(curiosity=0.5, energy=0.7)
        _patch_db.get_drives_state = AsyncMock(return_value=starting_drives)

        validated = _make_validated(monologue='Nothing interesting here at all.')
        bo = _make_body_output(read_results=[_make_read_result()])
        effects = await process_reflection(validated, bo)
        assert effects['boring'] is True

        # Check drives were adjusted
        calls = _patch_db.save_drives_state.call_args_list
        assert len(calls) >= 1
        saved_drives = calls[0][0][0]
        assert saved_drives.diversive_curiosity < 0.5  # drained
        assert saved_drives.energy < 0.7  # cost

    @pytest.mark.asyncio
    async def test_no_curiosity_drain_on_read(self):
        """read_content should NEVER appear in ACTION_DRIVE_EFFECTS with curiosity drain."""
        # Check ACTION_DRIVE_EFFECTS doesn't drain curiosity for any action
        for action, effects in ACTION_DRIVE_EFFECTS.items():
            assert 'curiosity' not in effects, \
                f"ACTION_DRIVE_EFFECTS['{action}'] still has curiosity drain"

    @pytest.mark.asyncio
    async def test_consumption_tracked(self, _patch_db):
        """Content pool item marked consumed after reflection."""
        validated = _make_validated(monologue='Interesting article about art.')
        bo = _make_body_output(read_results=[_make_read_result(content_id='c42')])
        await process_reflection(validated, bo)

        # update_pool_item should have been called with consumed=True
        calls = _patch_db.update_pool_item.call_args_list
        found_consumption = False
        for call in calls:
            kwargs = call[1] if call[1] else {}
            args = call[0] if call[0] else ()
            if kwargs.get('consumed') is True or (len(args) > 0 and args[0] == 'c42'):
                found_consumption = True
                break
        assert found_consumption, "Expected update_pool_item called with consumed=True"

    @pytest.mark.asyncio
    async def test_reflection_spawns_question(self, _patch_db):
        """Monologue with a question → question_raised effect."""
        validated = _make_validated(
            monologue='I wonder — how does photosynthesis actually convert light to energy?'
        )
        bo = _make_body_output(read_results=[_make_read_result()])

        # _extract_epistemic_question should pick up the question
        effects = await process_reflection(validated, bo)
        # The question detection is handled by EC processing in TASK-043
        # But our effect flag should be set if a question was found
        # Note: _extract_epistemic_question looks for "?" or "wonder" patterns
        assert effects['question_raised'] is True

    @pytest.mark.asyncio
    async def test_question_raises_arousal(self, _patch_db):
        """New question raised → mood_arousal bumped."""
        starting_drives = _make_drives(mood_arousal=0.3)
        _patch_db.get_drives_state = AsyncMock(return_value=starting_drives)

        validated = _make_validated(
            monologue='I wonder why some galaxies spiral and others dont?'
        )
        bo = _make_body_output(read_results=[_make_read_result()])
        await process_reflection(validated, bo)

        calls = _patch_db.save_drives_state.call_args_list
        found_arousal_bump = False
        for call in calls:
            drives = call[0][0]
            if drives.mood_arousal > 0.3:
                found_arousal_bump = True
                break
        assert found_arousal_bump, "Expected mood_arousal bump for question"
