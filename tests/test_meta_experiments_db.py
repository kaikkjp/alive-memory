"""Tests for db/meta_experiments.py — experiment log CRUD (TASK-090)."""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture
async def test_db(tmp_path):
    """Initialize a test database."""
    import importlib
    import db.connection as _conn
    # Restore real module if it got mocked
    if not hasattr(_conn, '__file__') or not hasattr(_conn, 'get_db'):
        _conn = importlib.import_module('db.connection')
        sys.modules['db.connection'] = _conn

    db_path = str(tmp_path / 'test.db')
    _conn._db = None
    _conn.DB_PATH = db_path
    await _conn.init_db()
    conn = await _conn.get_db()
    yield conn
    if _conn._db is not None:
        await _conn._db.close()
        _conn._db = None


@pytest.mark.asyncio
async def test_record_experiment(test_db):
    """Record an experiment and verify it's stored."""
    from db.meta_experiments import record_experiment
    exp_id = await record_experiment(
        cycle_at_change=100,
        param_name='hypothalamus.equilibria.diversive_curiosity',
        old_value=0.40,
        new_value=0.43,
        reason='initiative_rate is 0.05, target [0.12, 0.35]',
        target_metric='initiative_rate',
        metric_value_at_change=0.05,
    )
    assert exp_id is not None
    assert exp_id > 0


@pytest.mark.asyncio
async def test_get_recent_experiments(test_db):
    """Fetch recent experiments in descending order."""
    from db.meta_experiments import record_experiment, get_recent_experiments
    await record_experiment(100, 'param_a', 0.4, 0.43, 'reason1', 'M2', 0.05)
    await record_experiment(200, 'param_b', 0.3, 0.28, 'reason2', 'M7', 0.95)

    recent = await get_recent_experiments(limit=10)
    assert len(recent) == 2
    assert recent[0]['cycle_at_change'] == 200  # most recent first
    assert recent[1]['cycle_at_change'] == 100


@pytest.mark.asyncio
async def test_get_pending_experiments(test_db):
    """Fetch only pending experiments."""
    from db.meta_experiments import record_experiment, get_pending_experiments
    await record_experiment(100, 'param_a', 0.4, 0.43, 'r', 'M2', 0.05)
    await record_experiment(200, 'param_b', 0.3, 0.28, 'r', 'M7', 0.95)

    # Mark one as evaluated (use fixture connection directly)
    await test_db.execute(
        "UPDATE meta_experiments SET outcome = 'improved' WHERE param_name = 'param_a'"
    )
    await test_db.commit()

    pending = await get_pending_experiments()
    assert len(pending) == 1
    assert pending[0]['param_name'] == 'param_b'


@pytest.mark.asyncio
async def test_get_last_adjustment_cycle(test_db):
    """Get last adjustment cycle for a parameter."""
    from db.meta_experiments import record_experiment, get_last_adjustment_cycle
    await record_experiment(100, 'param_a', 0.4, 0.43, 'r', 'M2', 0.05)
    await record_experiment(300, 'param_a', 0.43, 0.46, 'r', 'M2', 0.08)

    last = await get_last_adjustment_cycle('param_a')
    assert last == 300


@pytest.mark.asyncio
async def test_get_last_adjustment_cycle_none(test_db):
    """Returns None for never-adjusted parameter."""
    from db.meta_experiments import get_last_adjustment_cycle
    last = await get_last_adjustment_cycle('nonexistent.param')
    assert last is None


@pytest.mark.asyncio
async def test_experiment_fields_complete(test_db):
    """All fields are stored and retrievable."""
    from db.meta_experiments import record_experiment, get_recent_experiments
    await record_experiment(
        cycle_at_change=150,
        param_name='hypothalamus.equilibria.mood_arousal',
        old_value=0.30,
        new_value=0.28,
        reason='emotional_range is 0.95, target [0.3, 0.8]',
        target_metric='emotional_range',
        metric_value_at_change=0.95,
    )

    experiments = await get_recent_experiments(limit=1)
    exp = experiments[0]
    assert exp['cycle_at_change'] == 150
    assert exp['param_name'] == 'hypothalamus.equilibria.mood_arousal'
    assert exp['old_value'] == 0.30
    assert exp['new_value'] == 0.28
    assert 'emotional_range' in exp['reason']
    assert exp['target_metric'] == 'emotional_range'
    assert exp['metric_value_at_change'] == 0.95
    assert exp['outcome'] == 'pending'
    assert exp['metric_value_after'] is None
    assert exp['reverted_at_cycle'] is None
    assert exp['created_at'] is not None
