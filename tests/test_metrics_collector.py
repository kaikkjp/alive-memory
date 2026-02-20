"""Tests for metrics collector, m_uptime, m_initiative, m_emotion (TASK-071 Phase 1)."""

import json
import pytest
import db
import clock
from metrics.collector import collect_hourly, collect_all, get_latest_snapshot, get_metric_trend
from metrics.m_uptime import compute as compute_uptime
from metrics.m_initiative import compute as compute_initiative
from metrics.m_emotion import compute as compute_emotion, _quantize, _normalize_valence
from metrics.models import MetricResult, MetricSnapshot


@pytest.fixture(autouse=True)
async def fresh_db(tmp_path):
    """Use a temp database for each test, with singleton rows seeded."""
    db._db = None
    original_path = db.DB_PATH
    db.DB_PATH = str(tmp_path / "test.db")
    await db.init_db()
    yield
    await db.close_db()
    db.DB_PATH = original_path


# ── Helpers ──

async def _insert_cycle(cycle_id: str, mode: str = 'ambient',
                         drives: dict = None):
    """Insert a cycle_log row for testing."""
    d = drives or {'mood_valence': 0.0, 'mood_arousal': 0.3, 'energy': 0.8}
    await db._exec_write(
        """INSERT INTO cycle_log
           (id, mode, drives, ts)
           VALUES (?, ?, ?, ?)""",
        (cycle_id, mode, json.dumps(d), clock.now_utc().isoformat()),
    )


async def _insert_action(cycle_id: str, action: str = 'journal_write',
                          status: str = 'executed'):
    """Insert an action_log row for testing."""
    import uuid
    action_id = str(uuid.uuid4())[:12]
    await db._exec_write(
        """INSERT INTO action_log
           (id, cycle_id, action, status, source)
           VALUES (?, ?, ?, ?, ?)""",
        (action_id, cycle_id, action, status, 'cortex'),
    )


# ── M1: Uptime ──

class TestM1Uptime:

    @pytest.mark.asyncio
    async def test_uptime_empty_db(self):
        result = await compute_uptime()
        assert result.name == 'uptime'
        assert result.value == 0.0
        assert result.details['cycles'] == 0

    @pytest.mark.asyncio
    async def test_uptime_with_cycles(self):
        await _insert_cycle('c1')
        await _insert_cycle('c2')
        await _insert_cycle('c3')
        result = await compute_uptime()
        assert result.value == 3.0
        assert result.details['cycles'] == 3
        assert result.details['days_alive'] >= 1

    @pytest.mark.asyncio
    async def test_uptime_display_format(self):
        await _insert_cycle('c1')
        result = await compute_uptime()
        assert 'Alive for' in result.display
        assert '1 cycle' in result.display


# ── M2: Initiative Rate ──

class TestM2Initiative:

    @pytest.mark.asyncio
    async def test_initiative_empty_db(self):
        result = await compute_initiative(hours=24)
        assert result.name == 'initiative_rate'
        assert result.value == 0.0
        assert result.details['total_actions'] == 0

    @pytest.mark.asyncio
    async def test_initiative_all_self(self):
        """All actions in ambient mode → 100% self-initiated."""
        await _insert_cycle('c1', mode='ambient')
        await _insert_action('c1', 'journal_write')
        await _insert_action('c1', 'browse_web')
        result = await compute_initiative(hours=24)
        assert result.value == 100.0
        assert result.details['self_initiated'] == 2

    @pytest.mark.asyncio
    async def test_initiative_mixed(self):
        """Mix of visitor and ambient cycles."""
        await _insert_cycle('c1', mode='visitor')
        await _insert_action('c1', 'respond')
        await _insert_cycle('c2', mode='ambient')
        await _insert_action('c2', 'journal_write')
        result = await compute_initiative(hours=24)
        assert result.value == 50.0
        assert result.details['self_initiated'] == 1
        assert result.details['visitor_triggered'] == 1

    @pytest.mark.asyncio
    async def test_initiative_only_executed_counted(self):
        """Suppressed actions should not be counted."""
        await _insert_cycle('c1', mode='ambient')
        await _insert_action('c1', 'journal_write', status='executed')
        await _insert_action('c1', 'browse_web', status='suppressed')
        result = await compute_initiative(hours=24)
        # Only 1 executed action
        assert result.details['total_actions'] == 1

    @pytest.mark.asyncio
    async def test_initiative_space_formatted_timestamps(self):
        """action_log.created_at uses CURRENT_TIMESTAMP (space format).

        Regression test: cutoff comparison must work with both ISO-8601
        and space-formatted timestamps (P1 review finding).
        """
        await _insert_cycle('c1', mode='ambient')
        # Insert with explicit space-formatted timestamp (CURRENT_TIMESTAMP format)
        import uuid
        action_id = str(uuid.uuid4())[:12]
        await db._exec_write(
            """INSERT INTO action_log
               (id, cycle_id, action, status, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (action_id, 'c1', 'journal_write', 'executed', 'cortex',
             clock.now_utc().strftime('%Y-%m-%d %H:%M:%S')),
        )
        result = await compute_initiative(hours=1)
        assert result.details['total_actions'] == 1, (
            "Space-formatted created_at must be found by datetime() comparison"
        )


# ── M7: Emotional Range ──

class TestM7EmotionalRange:

    def test_quantize_edges(self):
        assert _quantize(0.0) == 0
        assert _quantize(1.0) == 4
        assert _quantize(0.5) == 2
        assert _quantize(-0.1) == 0  # clamped
        assert _quantize(1.1) == 4   # clamped

    def test_normalize_valence(self):
        assert _normalize_valence(-1.0) == 0.0
        assert _normalize_valence(0.0) == 0.5
        assert _normalize_valence(1.0) == 1.0

    @pytest.mark.asyncio
    async def test_emotion_empty_db(self):
        result = await compute_emotion()
        assert result.name == 'emotional_range'
        assert result.value == 0.0
        assert result.details['states_visited'] == 0

    @pytest.mark.asyncio
    async def test_emotion_single_state(self):
        """One cycle = one mood state visited."""
        await _insert_cycle('c1', drives={
            'mood_valence': 0.0, 'mood_arousal': 0.3, 'energy': 0.8,
        })
        result = await compute_emotion()
        assert result.value == 1.0
        assert result.details['states_visited'] == 1
        assert result.details['cycles_analyzed'] == 1

    @pytest.mark.asyncio
    async def test_emotion_diverse_states(self):
        """Multiple distinct mood states → higher range."""
        states = [
            {'mood_valence': -0.8, 'mood_arousal': 0.1, 'energy': 0.2},  # low everything
            {'mood_valence': 0.8, 'mood_arousal': 0.9, 'energy': 0.9},   # high everything
            {'mood_valence': 0.0, 'mood_arousal': 0.5, 'energy': 0.5},   # mid
        ]
        for i, d in enumerate(states):
            await _insert_cycle(f'c{i}', drives=d)
        result = await compute_emotion()
        assert result.value >= 3.0  # at least 3 distinct bins

    @pytest.mark.asyncio
    async def test_emotion_same_state_repeated(self):
        """Same mood state repeated → still 1 bin."""
        for i in range(5):
            await _insert_cycle(f'c{i}', drives={
                'mood_valence': 0.0, 'mood_arousal': 0.3, 'energy': 0.8,
            })
        result = await compute_emotion()
        assert result.value == 1.0
        assert result.details['cycles_analyzed'] == 5


# ── Collector ──

class TestCollector:

    @pytest.mark.asyncio
    async def test_collect_all_returns_snapshot(self):
        await _insert_cycle('c1')
        snapshot = await collect_all()
        assert isinstance(snapshot, MetricSnapshot)
        assert len(snapshot.metrics) == 3
        names = {m.name for m in snapshot.metrics}
        assert names == {'uptime', 'initiative_rate', 'emotional_range'}

    @pytest.mark.asyncio
    async def test_collect_hourly_stores_snapshots(self):
        await _insert_cycle('c1')
        snapshot = await collect_hourly()
        assert len(snapshot.metrics) == 3

        # Verify stored in DB
        latest = await get_latest_snapshot('uptime')
        assert latest is not None
        assert latest['value'] == 1.0

    @pytest.mark.asyncio
    async def test_get_metric_trend_empty(self):
        trend = await get_metric_trend('uptime', days=30)
        assert trend == []

    @pytest.mark.asyncio
    async def test_get_metric_trend_after_collection(self):
        await _insert_cycle('c1')
        await collect_hourly()
        trend = await get_metric_trend('uptime', days=30, period='hourly')
        assert len(trend) >= 1
        assert trend[0]['value'] == 1.0


# ── Models ──

class TestModels:

    def test_metric_result_to_dict(self):
        r = MetricResult(name='test', value=42.0, details={'k': 'v'}, display='test: 42')
        d = r.to_dict()
        assert d['name'] == 'test'
        assert d['value'] == 42.0
        assert d['details'] == {'k': 'v'}
        assert d['display'] == 'test: 42'

    def test_metric_snapshot_to_dict(self):
        m = MetricResult(name='uptime', value=100.0)
        s = MetricSnapshot(timestamp='2026-01-01T00:00:00+00:00', period='hourly', metrics=[m])
        d = s.to_dict()
        assert d['period'] == 'hourly'
        assert len(d['metrics']) == 1
        assert d['metrics'][0]['name'] == 'uptime'
