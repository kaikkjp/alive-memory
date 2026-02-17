"""Tests for epistemic curiosity lifecycle.

TASK-043: Verifies EC creation, merge, decay, expiration, eviction,
reinforcement, and max active enforcement.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.event import Event
from models.pipeline import (
    ValidatedOutput, MotorPlan, BodyOutput, ActionResult,
)
from models.state import EpistemicCuriosity, EPISTEMIC_CONFIG
from pipeline.output import (
    _extract_epistemic_question,
    _topics_similar,
    _process_epistemic_curiosities,
)


@pytest.fixture(autouse=True)
def _patch_output_deps():
    """Patch db and clock at the pipeline.output module level."""
    mock_db = MagicMock()
    mock_db.get_drives_state = AsyncMock(return_value=MagicMock(
        social_hunger=0.5, curiosity=0.5, diversive_curiosity=0.5,
        expression_need=0.3, rest_need=0.2, energy=0.7,
        mood_valence=0.0, mood_arousal=0.3,
    ))
    mock_db.save_drives_state = AsyncMock(return_value=None)
    mock_db.append_event = AsyncMock(return_value=None)
    mock_db.get_active_epistemic_curiosities = AsyncMock(return_value=[])
    mock_db.upsert_epistemic_curiosity = AsyncMock(return_value=None)
    mock_db.evict_weakest_curiosity = AsyncMock(return_value=None)
    mock_db.get_executed_action_count_today = AsyncMock(return_value=0)

    mock_clock = MagicMock()
    mock_clock.now_utc = MagicMock(
        return_value=datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    )

    with patch('pipeline.output.db', mock_db), \
         patch('pipeline.output.clock', mock_clock):
        yield mock_db, mock_clock


@pytest.fixture
def mock_db(_patch_output_deps):
    return _patch_output_deps[0]


def _make_read_result(title='Test Article', content_id='content-123'):
    """Create a successful read_content ActionResult."""
    return ActionResult(
        action='read_content',
        success=True,
        payload={
            'title': title,
            'content_id': content_id,
            'full_content': 'Article text here.',
        },
    )


def _make_validated(monologue='', actions=None):
    """Create a ValidatedOutput."""
    return ValidatedOutput(
        dialogue='',
        internal_monologue=monologue,
        expression='neutral',
        approved_actions=actions or [],
    )


class TestECCreation:
    """EC created from gap detection with cortex engagement."""

    @pytest.mark.asyncio
    async def test_ec_created_from_gap(self, mock_db):
        """Epistemic gap score with cortex read → EC in DB."""
        body = BodyOutput(executed=[_make_read_result()])
        validated = _make_validated(monologue='Interesting. What else exists from this era?')

        await _process_epistemic_curiosities(validated, body)

        mock_db.upsert_epistemic_curiosity.assert_called_once()
        ec = mock_db.upsert_epistemic_curiosity.call_args.args[0]
        assert ec.topic == 'Test Article'
        assert ec.source_type == 'notification'
        assert ec.intensity == 0.5

    @pytest.mark.asyncio
    async def test_ec_gets_question_from_monologue(self, mock_db):
        """Question extracted from cortex internal monologue."""
        body = BodyOutput(executed=[_make_read_result()])
        validated = _make_validated(
            monologue='This reminds me of something. Are there more variants I haven\'t seen?')

        await _process_epistemic_curiosities(validated, body)

        ec = mock_db.upsert_epistemic_curiosity.call_args.args[0]
        assert '?' in ec.question
        assert 'variants' in ec.question.lower()

    @pytest.mark.asyncio
    async def test_ec_templates_question_when_none(self, mock_db):
        """Default question template when cortex doesn't articulate one."""
        body = BodyOutput(executed=[_make_read_result(title='Vintage Prism Cards')])
        validated = _make_validated(monologue='Interesting article.')

        await _process_epistemic_curiosities(validated, body)

        ec = mock_db.upsert_epistemic_curiosity.call_args.args[0]
        assert 'Vintage Prism Cards' in ec.question


class TestECMerge:
    """EC merge on similar topics."""

    @pytest.mark.asyncio
    async def test_ec_merged_on_similar(self, mock_db):
        """New question similar to existing → reinforced, no duplicate."""
        existing_ec = EpistemicCuriosity(
            id='ec-1', topic='Vintage Prism Cards',
            question='How many variants exist?',
            intensity=0.5, source_type='notification', source_id='x',
            created_at='2026-01-15T10:00:00+00:00',
            last_reinforced_at='2026-01-15T10:00:00+00:00',
        )
        mock_db.get_active_epistemic_curiosities = AsyncMock(return_value=[existing_ec])

        body = BodyOutput(executed=[_make_read_result(title='Vintage Prism Cards Guide')])
        validated = _make_validated()

        await _process_epistemic_curiosities(validated, body)

        # Should reinforce existing, not create new
        call = mock_db.upsert_epistemic_curiosity.call_args.args[0]
        assert call.id == 'ec-1'  # same EC
        assert call.intensity > 0.5  # reinforced


class TestECDecay:
    """EC decay over time (tested via DB function)."""

    @pytest.mark.asyncio
    async def test_ec_decays_over_time(self):
        """Intensity drops by decay_rate * hours."""
        from db.state import decay_epistemic_curiosities

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall = AsyncMock(return_value=[{
            'id': 'ec-1', 'topic': 'Test', 'question': 'Why?',
            'intensity': 0.5, 'source_type': 'notification', 'source_id': 'x',
            'created_at': '2026-01-15T10:00:00+00:00',
            'last_reinforced_at': '2026-01-15T10:00:00+00:00',
            'decay_rate': 0.02, 'resolved': 0, 'resolution_source': None,
        }])
        mock_conn.execute = AsyncMock(return_value=mock_cursor)

        with patch('db.state._connection') as mock_connection:
            mock_connection.get_db = AsyncMock(return_value=mock_conn)
            mock_connection._exec_write = AsyncMock()

            expired = await decay_epistemic_curiosities(elapsed_hours=1.0)

            # intensity = 0.5 - 0.02*1.0 = 0.48, not expired
            assert len(expired) == 0
            mock_connection._exec_write.assert_called_once()
            # Should update intensity to ~0.48
            call_args = mock_connection._exec_write.call_args
            assert call_args.args[1][0] == pytest.approx(0.48, abs=0.01)

    @pytest.mark.asyncio
    async def test_ec_expires_below_threshold(self):
        """Intensity < 0.05 → removed, marked as decayed."""
        from db.state import decay_epistemic_curiosities

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall = AsyncMock(return_value=[{
            'id': 'ec-1', 'topic': 'Fading Question', 'question': 'Why?',
            'intensity': 0.06, 'source_type': 'notification', 'source_id': 'x',
            'created_at': '2026-01-15T10:00:00+00:00',
            'last_reinforced_at': '2026-01-15T10:00:00+00:00',
            'decay_rate': 0.02, 'resolved': 0, 'resolution_source': None,
        }])
        mock_conn.execute = AsyncMock(return_value=mock_cursor)

        with patch('db.state._connection') as mock_connection:
            mock_connection.get_db = AsyncMock(return_value=mock_conn)
            mock_connection._exec_write = AsyncMock()

            expired = await decay_epistemic_curiosities(elapsed_hours=1.0)

            # intensity = 0.06 - 0.02 = 0.04 < 0.05 → expired
            assert len(expired) == 1
            assert expired[0].topic == 'Fading Question'
            assert expired[0].resolution_source == 'decayed'


class TestECEviction:
    """EC eviction at max active."""

    @pytest.mark.asyncio
    async def test_ec_eviction_at_max(self, mock_db):
        """6th question evicts weakest, seed created for evicted."""
        # 5 existing ECs (at max)
        existing = [
            EpistemicCuriosity(
                id=f'ec-{i}', topic=f'Topic {i}', question=f'Question {i}?',
                intensity=0.3 + i * 0.1, source_type='notification', source_id=f'x-{i}',
                created_at='2026-01-15T10:00:00+00:00',
                last_reinforced_at='2026-01-15T10:00:00+00:00',
            )
            for i in range(5)
        ]
        mock_db.get_active_epistemic_curiosities = AsyncMock(return_value=existing)
        evicted_ec = EpistemicCuriosity(
            id='ec-0', topic='Topic 0', question='Question 0?',
            intensity=0.3,
        )
        mock_db.evict_weakest_curiosity = AsyncMock(return_value=evicted_ec)

        # New article with different topic
        body = BodyOutput(executed=[_make_read_result(title='Brand New Subject')])
        validated = _make_validated()

        await _process_epistemic_curiosities(validated, body)

        # Should evict weakest
        mock_db.evict_weakest_curiosity.assert_called_once()
        # Should create reflection seed for evicted
        event_calls = mock_db.append_event.call_args_list
        seed_calls = [c for c in event_calls
                      if c.args[0].event_type == 'self_reflection_seed']
        assert len(seed_calls) == 1
        assert seed_calls[0].args[0].payload['ec_evicted'] is True

    @pytest.mark.asyncio
    async def test_ec_max_active_five(self, mock_db):
        """Never more than 5 active ECs — new one triggers eviction."""
        existing = [
            EpistemicCuriosity(
                id=f'ec-{i}', topic=f'Unique Topic {i}', question=f'Question {i}?',
                intensity=0.5, source_type='notification', source_id=f'x-{i}',
                created_at='2026-01-15T10:00:00+00:00',
                last_reinforced_at='2026-01-15T10:00:00+00:00',
            )
            for i in range(5)
        ]
        mock_db.get_active_epistemic_curiosities = AsyncMock(return_value=existing)
        mock_db.evict_weakest_curiosity = AsyncMock(return_value=existing[0])

        body = BodyOutput(executed=[_make_read_result(title='New Discovery')])
        validated = _make_validated()

        await _process_epistemic_curiosities(validated, body)

        # Eviction must have happened
        mock_db.evict_weakest_curiosity.assert_called_once()
        # And a new EC should be created
        mock_db.upsert_epistemic_curiosity.assert_called()


class TestECReinforcement:
    """EC reinforcement by related content."""

    @pytest.mark.asyncio
    async def test_ec_reinforced_by_related_content(self, mock_db):
        """Matching gap score boosts intensity +0.10."""
        existing_ec = EpistemicCuriosity(
            id='ec-1', topic='Vintage Cards Collection',
            question='Are there rare variants?',
            intensity=0.4, source_type='notification', source_id='x',
            created_at='2026-01-15T10:00:00+00:00',
            last_reinforced_at='2026-01-15T10:00:00+00:00',
        )
        mock_db.get_active_epistemic_curiosities = AsyncMock(return_value=[existing_ec])

        body = BodyOutput(executed=[_make_read_result(title='Vintage Cards Rare Variants')])
        validated = _make_validated()

        await _process_epistemic_curiosities(validated, body)

        ec = mock_db.upsert_epistemic_curiosity.call_args.args[0]
        assert ec.id == 'ec-1'
        assert ec.intensity == pytest.approx(0.5, abs=0.01)  # 0.4 + 0.10


class TestTopicSimilarity:
    """Tests for _topics_similar keyword overlap."""

    def test_similar_topics(self):
        assert _topics_similar('Vintage Prism Cards', 'Vintage Prism Cards Guide') is True

    def test_different_topics(self):
        assert _topics_similar('Vintage Prism Cards', 'Python Programming Language') is False

    def test_empty_topic(self):
        assert _topics_similar('', 'Something') is False


class TestExtractEpistemicQuestion:
    """Tests for _extract_epistemic_question."""

    def test_finds_question(self):
        q = _extract_epistemic_question('This is interesting. What else exists from this era?')
        assert '?' in q
        assert 'exists' in q.lower()

    def test_no_question(self):
        q = _extract_epistemic_question('This is just a statement.')
        assert q == ''

    def test_empty_monologue(self):
        assert _extract_epistemic_question('') == ''
        assert _extract_epistemic_question(None) == ''
