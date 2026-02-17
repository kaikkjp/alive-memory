"""Tests for TASK-045: Explicit reflection fields + totem/thread outputs.

Verifies: explicit CortexOutput fields override regex, totem weight updates,
thread touches, backward compat (regex fallback when fields absent),
CortexOutput.from_dict() parsing, and conversation context surfacing.
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Mock missing native deps before any pipeline import (env limitation)
for _mod in ('aiosqlite', 'anthropic', 'httpx'):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

import pytest

from models.pipeline import CortexOutput, ValidatedOutput, BodyOutput, ActionResult
from models.state import DrivesState, EpistemicCuriosity, EPISTEMIC_CONFIG


# ── Fixtures & helpers ──


def _make_body_output(read_results=None):
    bo = BodyOutput()
    if read_results:
        for r in read_results:
            bo.executed.append(r)
    return bo


def _make_read_result(content_id='c1', title='Test Article', success=True):
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


def _make_validated(monologue='', dialogue='', **reflection_fields):
    """Build a ValidatedOutput with optional explicit reflection fields."""
    return ValidatedOutput(
        internal_monologue=monologue,
        dialogue=dialogue or '...',
        expression='neutral',
        body_state='sitting',
        gaze='forward',
        **reflection_fields,
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


def _build_mock_db():
    mock_db = MagicMock()
    mock_db.update_pool_item = AsyncMock()
    mock_db.get_drives_state = AsyncMock(return_value=_make_drives())
    mock_db.save_drives_state = AsyncMock()
    mock_db.insert_text_fragment = AsyncMock()
    mock_db.get_active_epistemic_curiosities = AsyncMock(return_value=[])
    mock_db.resolve_epistemic_curiosity = AsyncMock()
    mock_db.get_totems = AsyncMock(return_value=[])
    mock_db.insert_totem = AsyncMock()
    mock_db.update_totem = AsyncMock()
    mock_db.get_thread_by_id = AsyncMock(return_value=None)
    mock_db.touch_thread = AsyncMock()
    return mock_db


# ── CortexOutput field parsing ──


class TestCortexOutputExplicitFields:
    """CortexOutput.from_dict() parses new reflection fields."""

    def test_explicit_fields_parsed(self):
        raw = {
            'internal_monologue': 'thinking',
            'reflection_memory': 'photons have dual nature',
            'reflection_question': 'what about gravitons?',
            'resolves_question': 'wave-particle duality',
            'relevant_to_visitor': 'v-abc',
            'relevant_to_thread': 't-xyz',
        }
        co = CortexOutput.from_dict(raw)
        assert co.reflection_memory == 'photons have dual nature'
        assert co.reflection_question == 'what about gravitons?'
        assert co.resolves_question == 'wave-particle duality'
        assert co.relevant_to_visitor == 'v-abc'
        assert co.relevant_to_thread == 't-xyz'

    def test_missing_fields_default_to_none(self):
        raw = {'internal_monologue': 'thinking'}
        co = CortexOutput.from_dict(raw)
        assert co.reflection_memory is None
        assert co.reflection_question is None
        assert co.resolves_question is None
        assert co.relevant_to_visitor is None
        assert co.relevant_to_thread is None

    def test_fields_carry_through_validated(self):
        co = CortexOutput(
            internal_monologue='test',
            reflection_memory='a memory',
            relevant_to_thread='t-1',
        )
        vo = ValidatedOutput.from_cortex(co)
        assert vo.reflection_memory == 'a memory'
        assert vo.relevant_to_thread == 't-1'
        assert vo.reflection_question is None


# ── Explicit fields override regex ──


class TestExplicitFieldOverridesRegex:
    """When explicit fields are present, regex patterns are skipped."""

    @pytest.mark.asyncio
    async def test_explicit_memory_overrides_regex(self):
        """Explicit reflection_memory is used instead of regex scan."""
        mock_db = _build_mock_db()
        with patch('pipeline.output.db', mock_db):
            from pipeline.output import process_reflection
            validated = _make_validated(
                monologue='Nothing special here.',
                reflection_memory='The concept of impermanence in art',
            )
            bo = _make_body_output(read_results=[_make_read_result()])
            effects = await process_reflection(validated, bo)
            assert effects['memory_created'] is True
            mock_db.insert_text_fragment.assert_called_once()
            call_kwargs = mock_db.insert_text_fragment.call_args[1]
            assert 'impermanence' in call_kwargs['content']

    @pytest.mark.asyncio
    async def test_explicit_question_overrides_regex(self):
        """Explicit reflection_question is used even without ? in monologue."""
        mock_db = _build_mock_db()
        with patch('pipeline.output.db', mock_db):
            from pipeline.output import process_reflection
            validated = _make_validated(
                monologue='Hmm, interesting.',
                reflection_question='How does entropy relate to time?',
            )
            bo = _make_body_output(read_results=[_make_read_result()])
            effects = await process_reflection(validated, bo)
            assert effects['question_raised'] is True

    @pytest.mark.asyncio
    async def test_explicit_resolution_overrides_regex(self):
        """Explicit resolves_question matches EC without needing regex."""
        mock_db = _build_mock_db()
        ec = _make_ec(topic='tidal forces', question='Why are tides irregular?')
        mock_db.get_active_epistemic_curiosities = AsyncMock(return_value=[ec])
        with patch('pipeline.output.db', mock_db):
            from pipeline.output import process_reflection
            validated = _make_validated(
                monologue='The article was clear.',
                resolves_question='tidal forces',
            )
            bo = _make_body_output(read_results=[
                _make_read_result(title='Ocean Dynamics'),
            ])
            effects = await process_reflection(validated, bo)
            assert effects['question_resolved'] is True
            mock_db.resolve_epistemic_curiosity.assert_called_once()


# ── Regex fallback when fields absent ──


class TestRegexFallbackPreserved:
    """When explicit fields are None, regex detection still works."""

    @pytest.mark.asyncio
    async def test_regex_memory_fallback(self):
        mock_db = _build_mock_db()
        with patch('pipeline.output.db', mock_db):
            from pipeline.output import process_reflection
            validated = _make_validated(
                monologue='I learned something fascinating about deep sea creatures.',
            )
            bo = _make_body_output(read_results=[_make_read_result()])
            effects = await process_reflection(validated, bo)
            assert effects['memory_created'] is True

    @pytest.mark.asyncio
    async def test_regex_question_fallback(self):
        mock_db = _build_mock_db()
        with patch('pipeline.output.db', mock_db):
            from pipeline.output import process_reflection
            validated = _make_validated(
                monologue='I wonder how photosynthesis converts light to energy?',
            )
            bo = _make_body_output(read_results=[_make_read_result()])
            effects = await process_reflection(validated, bo)
            assert effects['question_raised'] is True

    @pytest.mark.asyncio
    async def test_regex_resolution_fallback(self):
        mock_db = _build_mock_db()
        ec = _make_ec(topic='deep sea creatures', question='How deep?')
        mock_db.get_active_epistemic_curiosities = AsyncMock(return_value=[ec])
        with patch('pipeline.output.db', mock_db):
            from pipeline.output import process_reflection
            validated = _make_validated(
                monologue='Now I understand how deep sea creatures survive.',
            )
            bo = _make_body_output(read_results=[
                _make_read_result(title='Deep Sea Creatures'),
            ])
            effects = await process_reflection(validated, bo)
            assert effects['question_resolved'] is True


# ── Totem weight updates ──


class TestTotemWeightUpdate:
    """relevant_to_visitor triggers totem weight boost."""

    @pytest.mark.asyncio
    async def test_existing_totem_boosted(self):
        """Matching totem gets +0.1 weight."""
        from models.state import Totem
        mock_db = _build_mock_db()
        existing_totem = Totem(
            id='totem-1', entity='deep sea creatures', weight=0.5,
            visitor_id='v-abc', context='', category='content',
        )
        mock_db.get_totems = AsyncMock(return_value=[existing_totem])
        with patch('pipeline.output.db', mock_db):
            from pipeline.output import process_reflection
            validated = _make_validated(
                monologue='Fascinating article.',
                reflection_memory='Bioluminescence is remarkable',
                relevant_to_visitor='v-abc',
            )
            bo = _make_body_output(read_results=[
                _make_read_result(title='Deep Sea Creatures'),
            ])
            await process_reflection(validated, bo)
            mock_db.update_totem.assert_called_once()
            call_kwargs = mock_db.update_totem.call_args[1]
            assert call_kwargs['weight'] == pytest.approx(0.6, abs=0.01)

    @pytest.mark.asyncio
    async def test_no_matching_totem_creates_new(self):
        """No matching totem → creates new one at weight 0.3."""
        mock_db = _build_mock_db()
        mock_db.get_totems = AsyncMock(return_value=[])
        with patch('pipeline.output.db', mock_db):
            from pipeline.output import process_reflection
            validated = _make_validated(
                monologue='Interesting.',
                relevant_to_visitor='v-abc',
            )
            bo = _make_body_output(read_results=[
                _make_read_result(title='Quantum Physics'),
            ])
            await process_reflection(validated, bo)
            mock_db.insert_totem.assert_called_once()
            call_kwargs = mock_db.insert_totem.call_args[1]
            assert call_kwargs['visitor_id'] == 'v-abc'
            assert call_kwargs['weight'] == 0.3

    @pytest.mark.asyncio
    async def test_no_totem_update_without_field(self):
        """No relevant_to_visitor → no totem updates."""
        mock_db = _build_mock_db()
        with patch('pipeline.output.db', mock_db):
            from pipeline.output import process_reflection
            validated = _make_validated(
                monologue='I learned something interesting.',
            )
            bo = _make_body_output(read_results=[_make_read_result()])
            await process_reflection(validated, bo)
            mock_db.get_totems.assert_not_called()
            mock_db.update_totem.assert_not_called()
            mock_db.insert_totem.assert_not_called()


# ── Thread touches ──


class TestThreadTouch:
    """relevant_to_thread triggers thread touch."""

    @pytest.mark.asyncio
    async def test_thread_touched(self):
        """Existing thread gets touched with content title."""
        from models.state import Thread
        mock_db = _build_mock_db()
        thread = Thread(
            id='t-xyz', thread_type='question', title='Ocean mysteries',
            status='open', content='What lives in the deep?',
        )
        mock_db.get_thread_by_id = AsyncMock(return_value=thread)
        with patch('pipeline.output.db', mock_db):
            from pipeline.output import process_reflection
            validated = _make_validated(
                monologue='This connects to my thread.',
                relevant_to_thread='t-xyz',
            )
            bo = _make_body_output(read_results=[
                _make_read_result(title='Deep Sea Exploration'),
            ])
            effects = await process_reflection(validated, bo)
            assert effects['thread_touched'] is True
            mock_db.touch_thread.assert_called_once()
            call_kwargs = mock_db.touch_thread.call_args[1]
            assert call_kwargs['thread_id'] == 't-xyz'
            assert 'Deep Sea Exploration' in call_kwargs['reason']

    @pytest.mark.asyncio
    async def test_missing_thread_no_crash(self):
        """Thread ID not found → no crash, thread_touched stays False."""
        mock_db = _build_mock_db()
        mock_db.get_thread_by_id = AsyncMock(return_value=None)
        with patch('pipeline.output.db', mock_db):
            from pipeline.output import process_reflection
            validated = _make_validated(
                monologue='Connected.',
                relevant_to_thread='t-nonexistent',
            )
            bo = _make_body_output(read_results=[_make_read_result()])
            effects = await process_reflection(validated, bo)
            assert effects['thread_touched'] is False
            mock_db.touch_thread.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_thread_touch_without_field(self):
        """No relevant_to_thread → no thread operations."""
        mock_db = _build_mock_db()
        with patch('pipeline.output.db', mock_db):
            from pipeline.output import process_reflection
            validated = _make_validated(monologue='I learned something.')
            bo = _make_body_output(read_results=[_make_read_result()])
            effects = await process_reflection(validated, bo)
            assert effects['thread_touched'] is False
            mock_db.get_thread_by_id.assert_not_called()


# ── Conversation context surfacing ──


class TestConversationContextSurfacing:
    """_surface_relevant_content detects overlap between notifications and conversation."""

    def test_overlap_surfaced(self):
        """Matching keywords between notification and visitor speech → surfaced."""
        from pipeline.cortex import _surface_relevant_content
        from pipeline.sensorium import Perception
        import clock

        parts = []
        perceptions = [Perception(
            p_type='feed_notifications',
            source='feed',
            ts=clock.now_utc(),
            content='New article: Deep Ocean Exploration Methods',
            features={'content_ids': ['c1'], 'is_notification': True},
        )]
        conversation = [
            {'role': 'visitor', 'text': 'I have been reading about deep ocean research lately'},
        ]
        _surface_relevant_content(parts, perceptions, conversation)
        assert any('CONTENT RELEVANT TO CONVERSATION' in p for p in parts)

    def test_no_overlap_no_surfacing(self):
        """No keyword overlap → nothing surfaced."""
        from pipeline.cortex import _surface_relevant_content
        from pipeline.sensorium import Perception
        import clock

        parts = []
        perceptions = [Perception(
            p_type='feed_notifications',
            source='feed',
            ts=clock.now_utc(),
            content='New article: Quantum Computing Advances',
            features={'content_ids': ['c1'], 'is_notification': True},
        )]
        conversation = [
            {'role': 'visitor', 'text': 'I like cats and dogs'},
        ]
        _surface_relevant_content(parts, perceptions, conversation)
        assert not any('CONTENT RELEVANT TO CONVERSATION' in p for p in parts)

    def test_empty_conversation_no_surfacing(self):
        """No conversation → nothing surfaced."""
        from pipeline.cortex import _surface_relevant_content

        parts = []
        _surface_relevant_content(parts, [], [])
        assert len(parts) == 0
