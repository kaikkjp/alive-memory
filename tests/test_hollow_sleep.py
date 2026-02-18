"""Tests for TASK-047: Fix hollow sleep consolidation — salience calibration.

Verifies:
1. Moment creation for different cycle types (journal, thread, expression, visitor, idle)
2. Nap/sleep threshold hierarchy (nap=0.65 highlights, sleep=0.45 full day)
3. Daily summary non-empty after activity
4. Salience distribution across mixed cycles
5. TASK-045 salience engine feeds day_memory scoring
"""

import types
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

from tests.aiohttp_stub import ensure_aiohttp_stub

ensure_aiohttp_stub()

import db
import sleep
from db.parameters import p
from pipeline.day_memory import (
    compute_moment_salience,
    maybe_record_moment,
    DayMemoryEntry,
)


def _base_result(**overrides):
    """Minimal cycle result dict."""
    r = {'resonance': False, 'actions': [], 'internal_monologue': '', 'dialogue': ''}
    r.update(overrides)
    return r


def _base_ctx(**overrides):
    """Minimal cycle context dict."""
    c = {
        'cycle_id': 'test-cycle-001',
        'has_internal_conflict': False,
        'had_contradiction': False,
        'trust_level': 'stranger',
        'max_drive_delta': 0.0,
        'mode': 'idle',
        'event_ids': [],
    }
    c.update(overrides)
    return c


class _Tx:
    """Async context manager stub for db.transaction()."""
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        return False


# ─── Test 1: Journal creates moment with salience > 0.4 ───

class TestJournalCreatesMoment(unittest.IsolatedAsyncioTestCase):
    """Cycle with write_journal → moment with salience > 0.4."""

    def test_journal_cycle_salience_above_04(self):
        """A journal-writing cycle with resonance and content scores > 0.4."""
        score = compute_moment_salience(
            _base_result(
                resonance=True,
                internal_monologue='The light through the window changed today. '
                                   'Something about the way it caught the dust.',
                actions=[{
                    'type': 'write_journal',
                    'detail': {'text': 'I noticed the light. It felt different.'},
                }],
            ),
            _base_ctx(mode='express', max_drive_delta=0.06),
        )
        assert score > 0.4, f"Journal cycle scored {score}, expected > 0.4"


# ─── Test 2: Thread creates moment with salience > 0.5 ───

class TestThreadCreatesMoment(unittest.IsolatedAsyncioTestCase):
    """Cycle with thread work → moment with salience > 0.5."""

    def test_thread_cycle_salience_above_05(self):
        """A thread-working cycle scores > 0.5."""
        score = compute_moment_salience(
            _base_result(
                resonance=True,
                internal_monologue='This idea about patterns in visitor behavior '
                                   'keeps developing. I need to think more.',
                actions=[
                    {'type': 'thread_update'},
                    {'type': 'write_journal', 'detail': {'text': 'The thread deepens.'}},
                ],
            ),
            _base_ctx(mode='express', max_drive_delta=0.08),
        )
        assert score > 0.5, f"Thread cycle scored {score}, expected > 0.5"


# ─── Test 3: Expression creates moment with salience > 0.4 ───

class TestExpressionCreatesMoment(unittest.IsolatedAsyncioTestCase):
    """Cycle with express_thought → moment with salience > 0.4."""

    def test_expression_cycle_salience_above_04(self):
        """An express_thought cycle with resonance and decent monologue scores > 0.4."""
        score = compute_moment_salience(
            _base_result(
                resonance=True,
                internal_monologue='word ' * 40,  # 40 words — not trivial
                actions=[{'type': 'express_thought'}],
            ),
            _base_ctx(mode='express', max_drive_delta=0.06),
        )
        assert score > 0.4, f"Expression cycle scored {score}, expected > 0.4"


# ─── Test 4: Visitor creates high-salience moment > 0.7 ───

class TestVisitorCreatesHighSalienceMoment(unittest.IsolatedAsyncioTestCase):
    """Visitor interaction → moment with salience > 0.7."""

    def test_visitor_cycle_salience_above_07(self):
        """A rich visitor interaction cycle scores > 0.7."""
        score = compute_moment_salience(
            _base_result(
                resonance=True,
                internal_monologue='word ' * 50,
                dialogue='word ' * 40,
                actions=[
                    {'type': 'speak'},
                    {'type': 'write_journal', 'detail': {'text': 'A real conversation.'}},
                ],
            ),
            _base_ctx(
                mode='engage',
                trust_level='regular',
                max_drive_delta=0.15,
                visitor_id='v1',
                visitor_name='Yuki',
            ),
        )
        assert score > 0.7, f"Visitor cycle scored {score}, expected > 0.7"


# ─── Test 5: Idle fidget cycle → no moment ───

class TestIdleFidgetNoMoment(unittest.IsolatedAsyncioTestCase):
    """Idle cycle with only fidget → no moment created."""

    def test_idle_fidget_below_threshold(self):
        """An idle cycle with no meaningful signals scores below recording threshold."""
        score = compute_moment_salience(
            _base_result(resonance=False, internal_monologue='', dialogue=''),
            _base_ctx(mode='idle', max_drive_delta=0.01),
        )
        assert score < 0.35, f"Idle fidget scored {score}, expected < 0.35 (no moment)"

    async def test_idle_fidget_no_db_insert(self):
        """maybe_record_moment does NOT insert for an idle fidget cycle."""
        insert_mock = AsyncMock()
        with patch('pipeline.day_memory.db.insert_day_memory', insert_mock), \
             patch('pipeline.day_memory.db.get_max_event_salience_dynamic',
                   new=AsyncMock(return_value=0.0)):
            await maybe_record_moment(
                _base_result(resonance=False),
                _base_ctx(mode='idle', max_drive_delta=0.01),
            )
        insert_mock.assert_not_called()


# ─── Test 6: Nap processes high-salience moments ───

class TestNapProcessesHighSalience(unittest.IsolatedAsyncioTestCase):
    """Nap consolidation finds moments above 0.65."""

    async def test_nap_finds_high_salience_moments(self):
        """Nap consolidation processes top moments — those above 0.65 are available."""
        high_moment = types.SimpleNamespace(
            id='m-high', retry_count=0, visitor_id='v1',
            summary='A meaningful visitor conversation.',
            moment_type='resonance', tags=['visitor'],
            ts=datetime(2026, 2, 17, 10, 0, tzinfo=timezone.utc),
            salience=0.75,
        )
        low_moment = types.SimpleNamespace(
            id='m-low', retry_count=0, visitor_id=None,
            summary='Quiet idle moment.',
            moment_type='resonance', tags=[],
            ts=datetime(2026, 2, 17, 9, 0, tzinfo=timezone.utc),
            salience=0.48,
        )
        patches = [
            patch.object(sleep.db, 'get_top_unprocessed_moments',
                         new=AsyncMock(return_value=[high_moment, low_moment])),
            patch.object(sleep, 'gather_hot_context', new=AsyncMock(return_value={})),
            patch.object(sleep, 'sleep_reflect',
                         new=AsyncMock(return_value={'reflection': 'ok', 'memory_updates': []})),
            patch.object(sleep.db, 'transaction', new=lambda: _Tx()),
            patch.object(sleep.db, 'insert_journal', new=AsyncMock(return_value='j1')),
            patch.object(sleep.db, 'mark_day_memory_processed', new=AsyncMock()),
            patch.object(sleep.db, 'mark_moments_nap_processed', new=AsyncMock()),
        ]
        for pat in patches:
            pat.start()
        try:
            count = await sleep.nap_consolidate(top_n=3)
            assert count == 2, f"Expected 2 moments processed, got {count}"
            # Verify both moments were nap_processed (including high one > 0.65)
            sleep.db.mark_moments_nap_processed.assert_called_once()
            processed_ids = sleep.db.mark_moments_nap_processed.call_args[0][0]
            assert 'm-high' in processed_ids
        finally:
            for pat in patches:
                pat.stop()


# ─── Test 7: Night sleep processes moments above 0.45 not nap_processed ───

class TestSleepProcessesRemaining(unittest.IsolatedAsyncioTestCase):
    """Night sleep processes moments above 0.45 (not nap_processed)."""

    async def test_sleep_threshold_is_045(self):
        """sleep_cycle queries with min_salience=0.45 (not 0.65)."""
        assert p('sleep.consolidation.min_salience') == 0.45, (
            f"MIN_SLEEP_SALIENCE is {p('sleep.consolidation.min_salience')}, expected 0.45"
        )

    async def test_sleep_finds_moderate_salience_moments(self):
        """Night sleep retrieves moments at salience=0.50 (would miss at old 0.65)."""
        moderate_moment = types.SimpleNamespace(
            id='m-moderate', retry_count=0, visitor_id=None,
            summary='A quiet but real moment of self-expression.',
            moment_type='self_expression', tags=['journal'],
            ts=datetime(2026, 2, 17, 14, 0, tzinfo=timezone.utc),
            salience=0.50,
        )
        patches = [
            patch.object(sleep.db, 'get_engagement_state',
                         new=AsyncMock(return_value=types.SimpleNamespace(status='none'))),
            patch.object(sleep.db, 'get_unprocessed_day_memory',
                         new=AsyncMock(return_value=[moderate_moment])),
            patch.object(sleep, 'gather_hot_context', new=AsyncMock(return_value={})),
            patch.object(sleep, 'sleep_reflect',
                         new=AsyncMock(return_value={'reflection': 'reflected', 'memory_updates': []})),
            patch.object(sleep.db, 'transaction', new=lambda: _Tx()),
            patch.object(sleep.db, 'insert_journal', new=AsyncMock(return_value='j1')),
            patch.object(sleep.db, 'mark_day_memory_processed', new=AsyncMock()),
            patch.object(sleep, 'write_daily_summary', new=AsyncMock()),
            patch.object(sleep, 'review_trait_stability', new=AsyncMock()),
            patch.object(sleep, 'review_self_modifications', new=AsyncMock()),
            patch.object(sleep.db, 'promote_pending_actions', new=AsyncMock(return_value=[])),
            patch.object(sleep, 'manage_thread_lifecycle', new=AsyncMock()),
            patch.object(sleep, 'cleanup_content_pool', new=AsyncMock()),
            patch.object(sleep, 'reset_drives_for_morning', new=AsyncMock()),
            patch.object(sleep, 'flush_day_memory', new=AsyncMock()),
            patch.object(sleep.db, 'set_setting', new=AsyncMock()),
        ]
        for pat in patches:
            pat.start()
        try:
            result = await sleep.sleep_cycle()
            assert result >= 0, "sleep_cycle should return >= 0 (moments consolidated)"
            # Verify the moderate moment was processed (not skipped by threshold)
            sleep.db.mark_day_memory_processed.assert_called_once_with('m-moderate')
            # Verify sleep_reflect was called (LLM reflection happened)
            sleep.sleep_reflect.assert_called_once()
        finally:
            for pat in patches:
                pat.stop()


# ─── Test 8: Daily summary non-empty after activity ───

class TestDailySummaryNonEmpty(unittest.IsolatedAsyncioTestCase):
    """After a day with activity, daily_summary has moment_count > 0."""

    async def test_daily_summary_has_moments(self):
        """write_daily_summary records non-zero moment_count."""
        moments = [
            types.SimpleNamespace(
                id=f'm{i}', salience=0.5 + i * 0.05,
                moment_type='resonance', tags=[],
                ts=datetime(2026, 2, 17, 10 + i, 0, tzinfo=timezone.utc),
            )
            for i in range(3)
        ]
        reflections = [
            {'moment': m, 'reflection': {'reflection': f'thought {i}', 'memory_updates': []}}
            for i, m in enumerate(moments)
        ]
        journal_ids = ['j1', 'j2', 'j3']

        summary_captured = {}

        async def capture_summary(s):
            summary_captured.update(s)

        with patch.object(sleep.db, 'insert_daily_summary', side_effect=capture_summary), \
             patch.object(sleep.db, 'get_days_alive', new=AsyncMock(return_value=5)), \
             patch.object(sleep.clock, 'now', return_value=datetime(2026, 2, 17, 3, 0)):
            await sleep.write_daily_summary(moments, reflections, journal_ids)

        assert summary_captured['moment_count'] == 3, (
            f"Expected moment_count=3, got {summary_captured.get('moment_count')}"
        )
        assert len(summary_captured['moment_ids']) == 3
        assert len(summary_captured['journal_entry_ids']) == 3
        assert summary_captured['emotional_arc'] != 'quiet'


# ─── Test 9: Salience distribution spans 0.3-0.9 ───

class TestSalienceDistribution(unittest.IsolatedAsyncioTestCase):
    """After 50 mixed cycles, salience spans 0.3-0.9 (not clustered)."""

    def test_mixed_cycles_produce_diverse_scores(self):
        """50 mixed cycle types produce salience ranging from ~0.0 to ~0.9+."""
        scores = []

        # 10 idle cycles (should be ~0.0)
        for _ in range(10):
            s = compute_moment_salience(
                _base_result(), _base_ctx(mode='idle'),
            )
            scores.append(s)

        # 10 routine expression cycles with resonance (~0.35-0.45)
        for i in range(10):
            s = compute_moment_salience(
                _base_result(
                    resonance=True,
                    internal_monologue='word ' * (15 + i * 3),
                    actions=[{'type': 'express_thought'}],
                ),
                _base_ctx(mode='express', max_drive_delta=0.03 + i * 0.01),
            )
            scores.append(s)

        # 10 journal+thread cycles (~0.5-0.7)
        for i in range(10):
            s = compute_moment_salience(
                _base_result(
                    resonance=True,
                    internal_monologue='word ' * (20 + i * 5),
                    actions=[
                        {'type': 'thread_update'},
                        {'type': 'write_journal', 'detail': {'text': f'Entry {i}'}},
                    ],
                ),
                _base_ctx(mode='express', max_drive_delta=0.05 + i * 0.02),
            )
            scores.append(s)

        # 10 content consumption cycles (~0.4-0.6)
        for i in range(10):
            s = compute_moment_salience(
                _base_result(
                    resonance=True,
                    internal_monologue='word ' * (10 + i * 4),
                    actions=[{'type': 'collection_add'}],
                ),
                _base_ctx(channel='consume', max_drive_delta=0.04 + i * 0.015),
            )
            scores.append(s)

        # 10 visitor cycles (~0.7-1.0)
        for i in range(10):
            trust = ['stranger', 'returner', 'regular', 'familiar'][min(i // 3, 3)]
            s = compute_moment_salience(
                _base_result(
                    resonance=True,
                    internal_monologue='word ' * (30 + i * 5),
                    dialogue='word ' * (20 + i * 4),
                    actions=[
                        {'type': 'speak'},
                        {'type': 'write_journal', 'detail': {'text': f'Talked to visitor {i}'}},
                    ],
                ),
                _base_ctx(
                    mode='engage',
                    trust_level=trust,
                    max_drive_delta=0.10 + i * 0.02,
                    visitor_id=f'v{i}',
                ),
            )
            scores.append(s)

        # Verify distribution spans the expected range
        above_threshold = [s for s in scores if s >= 0.35]
        min_above = min(above_threshold) if above_threshold else 0
        max_score = max(scores)

        # TASK-053: wider modulation raises floor — express_thought base 0.40 + mods
        assert min_above < 0.60, f"Lowest above-threshold score is {min_above}, expected < 0.60"
        assert max_score > 0.80, f"Highest score is {max_score}, expected > 0.80"
        # Spread should be at least 0.30 (TASK-053 target)
        spread = max_score - min_above
        assert spread > 0.30, f"Spread {spread:.3f}, expected > 0.30"

        # Should have idle cycles below threshold and active cycles above
        below = [s for s in scores if s < 0.35]
        above = [s for s in scores if s >= 0.35]
        assert len(below) >= 5, f"Expected at least 5 below-threshold, got {len(below)}"
        assert len(above) >= 20, f"Expected at least 20 above-threshold, got {len(above)}"

        # Verify spread — scores should not cluster
        unique_rounded = set(round(s, 2) for s in scores if s > 0)
        assert len(unique_rounded) >= 10, (
            f"Expected at least 10 distinct scores (2dp), got {len(unique_rounded)}"
        )


# ─── Test 10: TASK-045 salience engine feeds day_memory ───

class TestSalienceEngineFeeds(unittest.IsolatedAsyncioTestCase):
    """Events with salience_dynamic > 0 from TASK-045 contribute to moment scoring."""

    def test_event_salience_dynamic_boosts_score(self):
        """event_salience_dynamic > 0 increases moment salience."""
        # Use engage mode to get a base above threshold for modulation to apply
        s_base = compute_moment_salience(
            _base_result(),
            _base_ctx(mode='engage', event_salience_dynamic=0.0),
        )
        s_boosted = compute_moment_salience(
            _base_result(),
            _base_ctx(mode='engage', event_salience_dynamic=0.5),
        )
        assert s_boosted > s_base, (
            f"salience_dynamic=0.5 should boost score: base={s_base}, boosted={s_boosted}"
        )
        # TASK-050: Contribution is min(0.05, 0.5 * 0.1) = 0.05
        assert abs(s_boosted - s_base - 0.05) < 0.001

    def test_event_salience_dynamic_caps_at_005(self):
        """Event salience contribution caps at 0.05 (TASK-050 modulation model)."""
        s_mid = compute_moment_salience(
            _base_result(),
            _base_ctx(mode='engage', event_salience_dynamic=0.5),
        )
        s_extreme = compute_moment_salience(
            _base_result(),
            _base_ctx(mode='engage', event_salience_dynamic=1.0),
        )
        # Both should get capped at 0.05
        assert abs(s_mid - s_extreme) < 0.001, (
            f"Both should cap at 0.05: mid={s_mid}, extreme={s_extreme}"
        )

    async def test_maybe_record_moment_fetches_event_salience(self):
        """maybe_record_moment enriches context with event salience from DB."""
        insert_mock = AsyncMock()
        get_sal_mock = AsyncMock(return_value=0.4)

        with patch('pipeline.day_memory.db.insert_day_memory', insert_mock), \
             patch('pipeline.day_memory.db.get_max_event_salience_dynamic', get_sal_mock), \
             patch('pipeline.day_memory.clock.now_utc',
                   return_value=datetime(2026, 2, 17, 12, 0, tzinfo=timezone.utc)):
            await maybe_record_moment(
                _base_result(
                    resonance=True,
                    internal_monologue='word ' * 30,
                    actions=[{'type': 'express_thought'}],
                ),
                _base_ctx(
                    mode='express',
                    max_drive_delta=0.05,
                    event_ids=['evt-1', 'evt-2'],
                ),
            )

        # DB lookup should have been called with the event IDs
        get_sal_mock.assert_called_once_with(['evt-1', 'evt-2'])
        # Moment should have been inserted (salience boosted above threshold)
        insert_mock.assert_called_once()
        # Check the inserted moment's salience includes the event boost
        inserted_moment = insert_mock.call_args[0][0]
        assert inserted_moment.salience > 0.4, (
            f"Inserted moment salience={inserted_moment.salience}, expected > 0.4"
        )

    def test_zero_event_salience_no_effect(self):
        """event_salience_dynamic=0.0 adds nothing to score."""
        s_none = compute_moment_salience(_base_result(), _base_ctx())
        s_zero = compute_moment_salience(
            _base_result(), _base_ctx(event_salience_dynamic=0.0),
        )
        assert s_none == s_zero
