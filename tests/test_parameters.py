"""Tests for db/parameters.py — CRUD, cache, bounds enforcement."""

import unittest
from unittest.mock import patch, AsyncMock

import aiosqlite

import db.parameters as params


# Minimal schema for self_parameters + parameter_modifications
_SCHEMA = """
CREATE TABLE self_parameters (
    key TEXT PRIMARY KEY,
    value REAL NOT NULL,
    default_value REAL NOT NULL,
    min_bound REAL,
    max_bound REAL,
    category TEXT NOT NULL DEFAULT 'test',
    description TEXT DEFAULT '',
    modified_by TEXT,
    modified_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE parameter_modifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    param_key TEXT NOT NULL,
    old_value REAL NOT NULL,
    new_value REAL NOT NULL,
    modified_by TEXT NOT NULL DEFAULT 'system',
    reason TEXT,
    ts TIMESTAMP NOT NULL
);
"""

# Seed rows for testing
_SEEDS = """
INSERT INTO self_parameters (key, value, default_value, min_bound, max_bound, category, description)
VALUES
    ('test.alpha', 0.5, 0.5, 0.0, 1.0, 'test', 'bounded 0-1'),
    ('test.beta', 10.0, 10.0, NULL, NULL, 'test', 'unbounded'),
    ('test.gamma', 0.3, 0.3, 0.0, 0.5, 'other', 'bounded 0-0.5');
"""


class ParametersCRUDTests(unittest.IsolatedAsyncioTestCase):
    """Test get_param, set_param, reset_param with a real in-memory DB."""

    async def asyncSetUp(self):
        self.conn = await aiosqlite.connect(":memory:")
        self.conn.row_factory = aiosqlite.Row
        for stmt in _SCHEMA.split(';'):
            if stmt.strip():
                await self.conn.execute(stmt.strip())
        for stmt in _SEEDS.split(';'):
            if stmt.strip():
                await self.conn.execute(stmt.strip())
        await self.conn.commit()

        # Patch db.connection so parameters.py talks to our in-memory DB
        self._get_db_patch = patch(
            'db.connection.get_db', new=AsyncMock(return_value=self.conn))
        self._exec_write_patch = patch(
            'db.connection._exec_write', new=self._exec_write_real)
        self._get_db_patch.start()
        self._exec_write_patch.start()

        # Populate cache
        await params.refresh_params_cache()

    async def _exec_write_real(self, sql, params_tuple=()):
        """Execute writes directly on our test connection."""
        await self.conn.execute(sql, params_tuple)
        await self.conn.commit()

    async def asyncTearDown(self):
        self._get_db_patch.stop()
        self._exec_write_patch.stop()
        await self.conn.close()
        # Reset module state
        params._cache.clear()
        params._known_keys.clear()

    # ── p() and p_or() ──

    async def test_p_returns_cached_value(self):
        assert params.p('test.alpha') == 0.5

    async def test_p_raises_on_unknown_key(self):
        with self.assertRaises(KeyError):
            params.p('nonexistent.key')

    async def test_p_or_returns_default_on_miss(self):
        assert params.p_or('nonexistent.key', 99.0) == 99.0

    async def test_p_or_returns_cached_on_hit(self):
        assert params.p_or('test.beta', 99.0) == 10.0

    # ── refresh_params_cache ──

    async def test_refresh_loads_all_params(self):
        cache = await params.refresh_params_cache()
        assert len(cache) == 3
        assert cache['test.alpha'] == 0.5
        assert cache['test.beta'] == 10.0
        assert cache['test.gamma'] == 0.3

    # ── get_param ──

    async def test_get_param_returns_full_record(self):
        record = await params.get_param('test.alpha')
        assert record is not None
        assert record['key'] == 'test.alpha'
        assert record['value'] == 0.5
        assert record['min_bound'] == 0.0
        assert record['max_bound'] == 1.0

    async def test_get_param_unknown_returns_none(self):
        record = await params.get_param('does.not.exist')
        assert record is None

    # ── set_param ──

    async def test_set_param_updates_value(self):
        result = await params.set_param('test.alpha', 0.8, 'test')
        assert result['value'] == 0.8
        # Cache updated immediately
        assert params.p('test.alpha') == 0.8

    async def test_set_param_rejects_below_min(self):
        with self.assertRaises(ValueError) as ctx:
            await params.set_param('test.alpha', -0.1, 'test')
        assert 'below minimum' in str(ctx.exception)
        # Value unchanged
        assert params.p('test.alpha') == 0.5

    async def test_set_param_rejects_above_max(self):
        with self.assertRaises(ValueError) as ctx:
            await params.set_param('test.alpha', 1.5, 'test')
        assert 'above maximum' in str(ctx.exception)
        assert params.p('test.alpha') == 0.5

    async def test_set_param_allows_unbounded(self):
        """Parameters with NULL bounds accept any value."""
        result = await params.set_param('test.beta', -999.0, 'test')
        assert result['value'] == -999.0
        assert params.p('test.beta') == -999.0

    async def test_set_param_unknown_key_raises(self):
        with self.assertRaises(ValueError) as ctx:
            await params.set_param('nonexistent', 1.0, 'test')
        assert 'Unknown parameter' in str(ctx.exception)

    async def test_set_param_logs_modification(self):
        await params.set_param('test.alpha', 0.7, 'operator', reason='tuning')
        log = await params.get_modification_log('test.alpha', limit=1)
        assert len(log) == 1
        assert log[0]['old_value'] == 0.5
        assert log[0]['new_value'] == 0.7
        assert log[0]['modified_by'] == 'operator'
        assert log[0]['reason'] == 'tuning'

    async def test_set_param_boundary_values_accepted(self):
        """Exact min and max bounds should be accepted."""
        await params.set_param('test.alpha', 0.0, 'test')
        assert params.p('test.alpha') == 0.0
        await params.set_param('test.alpha', 1.0, 'test')
        assert params.p('test.alpha') == 1.0

    # ── reset_param ──

    async def test_reset_restores_default(self):
        await params.set_param('test.alpha', 0.9, 'test')
        assert params.p('test.alpha') == 0.9
        result = await params.reset_param('test.alpha', 'test')
        assert result['value'] == 0.5
        assert params.p('test.alpha') == 0.5

    async def test_reset_logs_modification(self):
        await params.set_param('test.alpha', 0.9, 'test')
        await params.reset_param('test.alpha', 'operator')
        log = await params.get_modification_log('test.alpha', limit=1)
        assert log[0]['reason'] == 'reset to default'

    async def test_reset_unknown_key_raises(self):
        with self.assertRaises(ValueError):
            await params.reset_param('nonexistent', 'test')

    # ── get_params_by_category ──

    async def test_get_params_by_category(self):
        results = await params.get_params_by_category('test')
        assert len(results) == 2
        keys = [r['key'] for r in results]
        assert 'test.alpha' in keys
        assert 'test.beta' in keys

    async def test_get_params_by_category_empty(self):
        results = await params.get_params_by_category('nonexistent')
        assert results == []

    # ── get_all_params ──

    async def test_get_all_params(self):
        results = await params.get_all_params()
        assert len(results) == 3

    # ── get_modification_log ──

    async def test_modification_log_empty(self):
        log = await params.get_modification_log()
        assert log == []

    async def test_modification_log_unfiltered(self):
        await params.set_param('test.alpha', 0.6, 'a')
        await params.set_param('test.beta', 5.0, 'b')
        log = await params.get_modification_log(limit=10)
        assert len(log) == 2

    # ── validate_cache ──

    async def test_validate_cache_healthy(self):
        warnings = params.validate_cache()
        assert warnings == []

    async def test_validate_cache_empty(self):
        params._cache.clear()
        warnings = params.validate_cache()
        assert any('empty' in w for w in warnings)


class SensoriumTrustFallbackTest(unittest.TestCase):
    """Regression: unknown trust_level must not crash (P1 review finding)."""

    def test_calculate_salience_unknown_trust(self):
        from pipeline.sensorium import calculate_salience
        from models.state import DrivesState, Visitor
        from models.event import Event

        drives = DrivesState(social_hunger=0.5, curiosity=0.5,
                             expression_need=0.3, rest_need=0.2,
                             energy=0.7, mood_valence=0.0, mood_arousal=0.3)
        event = Event(event_type='visitor_message', source='chat',
                      payload={'text': 'hello'})
        visitor = Visitor(id='v1', trust_level='vip')  # unknown trust

        # Must not raise — falls back to 0.0 bonus
        result = calculate_salience(event, drives, visitor)
        assert 0.0 <= result <= 1.0

    def test_calculate_connect_salience_unknown_trust(self):
        from pipeline.sensorium import calculate_connect_salience
        from models.state import DrivesState

        drives = DrivesState(social_hunger=0.5, curiosity=0.5,
                             expression_need=0.3, rest_need=0.2,
                             energy=0.7, mood_valence=0.0, mood_arousal=0.3)

        # Must not raise — falls back to 0.0 bonus
        result = calculate_connect_salience(drives, 'vip')
        assert 0.0 <= result <= 1.0
