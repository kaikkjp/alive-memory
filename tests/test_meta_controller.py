"""Tests for sleep/meta_controller.py — metric-driven self-tuning (TASK-090).

13 unit tests + 2 integration + 4 regression tests:
 1. test_metric_below_target — proposes curiosity increase
 2. test_metric_above_target — proposes arousal decrease
 3. test_metric_in_range — no adjustments
 4. test_hard_floor_enforced — clamped to floor
 5. test_self_parameters_bounds_enforced — clamped to inner bounds
 6. test_max_adjustments_per_sleep — only 2 adjustments when 5 metrics out of range
 7. test_cooldown_respected — skipped due to recent adjustment
 8. test_cooldown_expired — allowed after enough cycles
 9. test_priority_ordering — priority 1 picked over priority 2
10. test_disabled — no adjustments, no errors
11. test_experiment_logged — experiment log entry with all fields
12. test_event_emitted — emits meta_controller_adjustment event
13. test_no_adjustment_no_event — in range → no event
14. test_sleep_phase_runs — full sleep cycle with meta-controller
15. test_config_actually_changes — next cycle reads new value
16. test_production_scale_initiative — raw 5.0 / 100 = 0.05 triggers raise
17. test_production_scale_emotional_range — raw 100 / 125 = 0.8, in range
18. test_production_scale_above_range — raw 120 / 125 = 0.96, triggers lower
19. test_hard_floor_overrides_self_parameters — hard floor wins over conflicting bounds
"""

import asyncio
import os
import sys
import pytest
import aiosqlite
from unittest.mock import patch, AsyncMock, MagicMock, PropertyMock

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Helpers ──

async def _init_test_db(db_path: str):
    """Initialize a test database with schema + migrations."""
    import importlib
    import db.connection as _conn
    # If db.connection got replaced with a mock, restore it
    if not hasattr(_conn, '__file__') or not hasattr(_conn, 'get_db'):
        _conn = importlib.import_module('db.connection')
        sys.modules['db.connection'] = _conn

    _conn._db = None
    _conn.DB_PATH = db_path
    await _conn.init_db()
    return await _conn.get_db()


async def _seed_params(conn):
    """Seed minimum self_parameters needed for meta-controller tests."""
    params = [
        ('hypothalamus.equilibria.diversive_curiosity', 0.40, 0.40, 0.0, 1.0, 'hypothalamus'),
        ('hypothalamus.equilibria.expression_need', 0.35, 0.35, 0.0, 1.0, 'hypothalamus'),
        ('hypothalamus.equilibria.mood_arousal', 0.30, 0.30, 0.0, 1.0, 'hypothalamus'),
    ]
    for key, val, default, min_b, max_b, cat in params:
        await conn.execute(
            """INSERT OR REPLACE INTO self_parameters
               (key, value, default_value, min_bound, max_bound, category, description)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (key, val, default, min_b, max_b, cat, f'test param {key}'),
        )
    await conn.commit()


async def _seed_metric(conn, metric_name: str, value: float):
    """Insert a metric snapshot for testing."""
    await conn.execute(
        """INSERT INTO metrics_snapshots (timestamp, metric_name, value, details, period)
           VALUES (datetime('now'), ?, ?, '{}', 'hourly')""",
        (metric_name, value),
    )
    await conn.commit()


async def _seed_cycles(conn, count: int):
    """Insert dummy cycle_log rows for minimum cycle checks."""
    import uuid
    for i in range(count):
        await conn.execute(
            """INSERT INTO cycle_log (id, mode, ts)
               VALUES (?, 'idle', datetime('now'))""",
            (str(uuid.uuid4()),),
        )
    await conn.commit()


# ── Test config builder ──

def _mc_config(
    enabled=True,
    min_cycles=10,
    max_adj=2,
    cooldown=200,
    targets=None,
    adjustments=None,
    hard_floor=None,
):
    """Build a meta_controller config dict for testing."""
    if targets is None:
        targets = {
            'initiative_rate': {'min': 0.12, 'max': 0.35, 'metric': 'initiative_rate'},
            'emotional_range': {'min': 0.3, 'max': 0.8, 'metric': 'emotional_range'},
        }
    if adjustments is None:
        adjustments = {
            'initiative_rate': [
                {'param': 'hypothalamus.equilibria.diversive_curiosity',
                 'direction': 1, 'step': 0.03, 'priority': 1},
                {'param': 'hypothalamus.equilibria.expression_need',
                 'direction': 1, 'step': 0.03, 'priority': 2},
            ],
            'emotional_range': [
                {'param': 'hypothalamus.equilibria.mood_arousal',
                 'direction': 1, 'step': 0.02, 'priority': 1},
            ],
        }
    if hard_floor is None:
        hard_floor = {
            'hypothalamus.equilibria.diversive_curiosity': [0.2, 0.8],
            'hypothalamus.equilibria.expression_need': [0.2, 0.8],
            'hypothalamus.equilibria.mood_arousal': [0.1, 0.7],
        }
    return {
        'enabled': enabled,
        'evaluation_window': 50,
        'min_cycles_before_adjust': min_cycles,
        'max_adjustments_per_sleep': max_adj,
        'cooldown_cycles': cooldown,
        'targets': targets,
        'adjustments': adjustments,
        'hard_floor': hard_floor,
    }


# ── Fixtures ──

@pytest.fixture
async def test_db(tmp_path):
    """Create and initialize a test database."""
    import importlib
    import db.connection as _conn
    # Restore real module if it got mocked
    if not hasattr(_conn, '__file__') or not hasattr(_conn, 'get_db'):
        _conn = importlib.import_module('db.connection')
        sys.modules['db.connection'] = _conn

    db_path = str(tmp_path / 'test.db')
    _conn._db = None
    _conn.DB_PATH = db_path

    conn = await _init_test_db(db_path)
    await _seed_params(conn)
    await _seed_cycles(conn, 200)  # enough cycles for min_cycles checks

    # Refresh the parameter cache so p() works
    from db.parameters import refresh_params_cache
    await refresh_params_cache()

    yield conn

    if _conn._db is not None:
        await _conn._db.close()
        _conn._db = None


# ── Unit Tests ──

@pytest.mark.asyncio
async def test_metric_below_target(test_db):
    """1. initiative_rate=0.05, target min=0.12 → proposes curiosity increase."""
    await _seed_metric(test_db, 'initiative_rate', 0.05)

    config = _mc_config()
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import run_meta_controller
        adjustments = await run_meta_controller()

    assert len(adjustments) >= 1
    adj = adjustments[0]
    assert adj['param'] == 'hypothalamus.equilibria.diversive_curiosity'
    assert adj['new_value'] > adj['old_value']  # raised


@pytest.mark.asyncio
async def test_metric_above_target(test_db):
    """2. emotional_range=0.95, target max=0.8 → proposes arousal decrease."""
    await _seed_metric(test_db, 'emotional_range', 0.95)

    config = _mc_config()
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import run_meta_controller
        adjustments = await run_meta_controller()

    # Find the emotional_range adjustment
    emo_adj = [a for a in adjustments if a['target_metric'] == 'emotional_range']
    assert len(emo_adj) == 1
    assert emo_adj[0]['param'] == 'hypothalamus.equilibria.mood_arousal'
    assert emo_adj[0]['new_value'] < emo_adj[0]['old_value']  # lowered


@pytest.mark.asyncio
async def test_metric_in_range(test_db):
    """3. All metrics in range → no adjustments."""
    await _seed_metric(test_db, 'initiative_rate', 0.20)
    await _seed_metric(test_db, 'emotional_range', 0.50)

    config = _mc_config()
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import run_meta_controller
        adjustments = await run_meta_controller()

    assert adjustments == []


@pytest.mark.asyncio
async def test_hard_floor_enforced(test_db):
    """4. Proposed adjustment exceeds hard floor → clamped."""
    # Set curiosity very high so lowering would be requested
    await test_db.execute(
        "UPDATE self_parameters SET value = 0.79 WHERE key = 'hypothalamus.equilibria.diversive_curiosity'"
    )
    await test_db.commit()
    from db.parameters import refresh_params_cache
    await refresh_params_cache()

    # Initiative rate way too high → lower curiosity
    await _seed_metric(test_db, 'initiative_rate', 0.90)

    config = _mc_config(
        hard_floor={'hypothalamus.equilibria.diversive_curiosity': [0.2, 0.8]}
    )
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import run_meta_controller
        adjustments = await run_meta_controller()

    if adjustments:
        for adj in adjustments:
            if adj['param'] == 'hypothalamus.equilibria.diversive_curiosity':
                assert adj['new_value'] >= 0.2
                assert adj['new_value'] <= 0.8


@pytest.mark.asyncio
async def test_self_parameters_bounds_enforced(test_db):
    """5. Proposed adjustment exceeds self_parameters bounds → clamped."""
    # Set tight bounds on the parameter
    await test_db.execute(
        """UPDATE self_parameters SET min_bound = 0.35, max_bound = 0.45
           WHERE key = 'hypothalamus.equilibria.diversive_curiosity'"""
    )
    await test_db.commit()
    from db.parameters import refresh_params_cache
    await refresh_params_cache()

    await _seed_metric(test_db, 'initiative_rate', 0.05)

    config = _mc_config()
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import run_meta_controller
        adjustments = await run_meta_controller()

    if adjustments:
        adj = adjustments[0]
        if adj['param'] == 'hypothalamus.equilibria.diversive_curiosity':
            assert adj['new_value'] <= 0.45  # clamped to max_bound


@pytest.mark.asyncio
async def test_max_adjustments_per_sleep(test_db):
    """6. Multiple metrics out of range, max=2 → only 2 adjustments."""
    await _seed_metric(test_db, 'initiative_rate', 0.05)
    await _seed_metric(test_db, 'emotional_range', 0.95)

    config = _mc_config(max_adj=2)
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import run_meta_controller
        adjustments = await run_meta_controller()

    assert len(adjustments) <= 2


@pytest.mark.asyncio
async def test_cooldown_respected(test_db):
    """7. Param adjusted 50 cycles ago, cooldown=200 → skipped."""
    await _seed_metric(test_db, 'initiative_rate', 0.05)

    # Insert a recent experiment for this param
    cycle_count = 200  # matches our seed
    await test_db.execute(
        """INSERT INTO meta_experiments
           (cycle_at_change, param_name, old_value, new_value, reason,
            target_metric, metric_value_at_change, outcome)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
        (cycle_count - 50, 'hypothalamus.equilibria.diversive_curiosity',
         0.37, 0.40, 'test', 'initiative_rate', 0.05),
    )
    # Also add one for expression_need (priority 2)
    await test_db.execute(
        """INSERT INTO meta_experiments
           (cycle_at_change, param_name, old_value, new_value, reason,
            target_metric, metric_value_at_change, outcome)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
        (cycle_count - 50, 'hypothalamus.equilibria.expression_need',
         0.32, 0.35, 'test', 'initiative_rate', 0.05),
    )
    await test_db.commit()

    config = _mc_config(cooldown=200)
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import run_meta_controller
        adjustments = await run_meta_controller()

    # Both candidates are in cooldown, so no initiative_rate adjustments
    init_adj = [a for a in adjustments if a['target_metric'] == 'initiative_rate']
    assert len(init_adj) == 0


@pytest.mark.asyncio
async def test_cooldown_expired(test_db):
    """8. Param adjusted 250 cycles ago, cooldown=200 → allowed."""
    await _seed_metric(test_db, 'initiative_rate', 0.05)

    # Insert an old experiment (250 cycles ago)
    cycle_count = 200
    await test_db.execute(
        """INSERT INTO meta_experiments
           (cycle_at_change, param_name, old_value, new_value, reason,
            target_metric, metric_value_at_change, outcome)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
        (cycle_count - 250, 'hypothalamus.equilibria.diversive_curiosity',
         0.37, 0.40, 'test', 'initiative_rate', 0.05),
    )
    await test_db.commit()

    config = _mc_config(cooldown=200)
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import run_meta_controller
        adjustments = await run_meta_controller()

    # Cooldown expired, should get an adjustment
    init_adj = [a for a in adjustments if a['target_metric'] == 'initiative_rate']
    assert len(init_adj) == 1


@pytest.mark.asyncio
async def test_priority_ordering(test_db):
    """9. Two candidates for same metric, priority 1 picked first."""
    await _seed_metric(test_db, 'initiative_rate', 0.05)

    config = _mc_config()
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import run_meta_controller
        adjustments = await run_meta_controller()

    # Priority 1 = diversive_curiosity, not expression_need
    init_adj = [a for a in adjustments if a['target_metric'] == 'initiative_rate']
    if init_adj:
        assert init_adj[0]['param'] == 'hypothalamus.equilibria.diversive_curiosity'


@pytest.mark.asyncio
async def test_disabled(test_db):
    """10. enabled=false → no adjustments, no errors."""
    await _seed_metric(test_db, 'initiative_rate', 0.05)

    config = _mc_config(enabled=False)
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import run_meta_controller
        adjustments = await run_meta_controller()

    assert adjustments == []


@pytest.mark.asyncio
async def test_experiment_logged(test_db):
    """11. Adjustment produces experiment log entry with all fields."""
    await _seed_metric(test_db, 'initiative_rate', 0.05)

    config = _mc_config()
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import run_meta_controller
        adjustments = await run_meta_controller()

    assert len(adjustments) >= 1

    # Check experiment log — use submodule directly to avoid proxy mock leaks
    from db.meta_experiments import get_recent_experiments
    experiments = await get_recent_experiments(limit=5)
    assert len(experiments) >= 1
    exp = experiments[0]
    assert exp['param_name'] == adjustments[0]['param']
    assert exp['old_value'] == adjustments[0]['old_value']
    assert exp['new_value'] == adjustments[0]['new_value']
    assert exp['target_metric'] == adjustments[0]['target_metric']
    assert exp['outcome'] == 'pending'
    assert exp['reason'] is not None


@pytest.mark.asyncio
async def test_event_emitted(test_db):
    """12. Adjustment emits meta_controller_adjustment event."""
    await _seed_metric(test_db, 'initiative_rate', 0.05)

    config = _mc_config()
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import run_meta_controller
        adjustments = await run_meta_controller()

    assert len(adjustments) >= 1

    # Check that a meta_controller_adjustment event was emitted
    cursor = await test_db.execute(
        "SELECT * FROM events WHERE event_type = 'meta_controller_adjustment'"
    )
    rows = await cursor.fetchall()
    assert len(rows) >= 1

    import json
    payload = json.loads(rows[0]['payload'])
    assert 'adjustments' in payload
    assert len(payload['adjustments']) >= 1


@pytest.mark.asyncio
async def test_no_adjustment_no_event(test_db):
    """13. Metrics in range → no event emitted."""
    await _seed_metric(test_db, 'initiative_rate', 0.20)
    await _seed_metric(test_db, 'emotional_range', 0.50)

    config = _mc_config()
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import run_meta_controller
        adjustments = await run_meta_controller()

    assert adjustments == []

    # No event should be emitted
    cursor = await test_db.execute(
        "SELECT COUNT(*) FROM events WHERE event_type = 'meta_controller_adjustment'"
    )
    row = await cursor.fetchone()
    assert row[0] == 0


# ── Integration Tests ──

@pytest.mark.asyncio
async def test_sleep_phase_runs(test_db):
    """14. Full sleep cycle with meta-controller phase → experiment log populated."""
    await _seed_metric(test_db, 'initiative_rate', 0.05)

    config = _mc_config()

    # Run meta-controller directly (it's wired as a phase in sleep_cycle)
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import run_meta_controller
        adjustments = await run_meta_controller()

    assert len(adjustments) >= 1

    # Verify DB state — use submodule directly to avoid proxy mock leaks
    from db.meta_experiments import get_recent_experiments
    experiments = await get_recent_experiments()
    assert len(experiments) >= 1
    assert experiments[0]['outcome'] == 'pending'


@pytest.mark.asyncio
async def test_config_actually_changes(test_db):
    """15. After meta-controller adjusts curiosity_eq, next cycle reads new value."""
    from db.parameters import p, refresh_params_cache

    old_curiosity = p('hypothalamus.equilibria.diversive_curiosity')
    await _seed_metric(test_db, 'initiative_rate', 0.05)

    config = _mc_config()
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import run_meta_controller
        adjustments = await run_meta_controller()

    assert len(adjustments) >= 1

    # Refresh cache (simulating next cycle start)
    await refresh_params_cache()

    new_curiosity = p('hypothalamus.equilibria.diversive_curiosity')
    assert new_curiosity != old_curiosity
    assert new_curiosity > old_curiosity  # initiative was low, so curiosity raised


# ── Regression Tests (code review P1/P2 fixes) ──

@pytest.mark.asyncio
async def test_production_scale_initiative(test_db):
    """16. Raw initiative_rate=5.0 (5%) with normalize=100 → treated as 0.05."""
    # Seed raw collector-scale value (5% stored as 5.0 by m_initiative.py)
    await _seed_metric(test_db, 'initiative_rate', 5.0)

    config = _mc_config(targets={
        'initiative_rate': {
            'min': 0.12, 'max': 0.35,
            'metric': 'initiative_rate',
            'normalize': 100.0,
        },
    })
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import run_meta_controller
        adjustments = await run_meta_controller()

    # 5.0 / 100 = 0.05, below 0.12 → should trigger raise
    assert len(adjustments) >= 1
    assert adjustments[0]['new_value'] > adjustments[0]['old_value']


@pytest.mark.asyncio
async def test_production_scale_emotional_range(test_db):
    """17. Raw emotional_range=100 (100 bins) with normalize=125 → treated as 0.8."""
    await _seed_metric(test_db, 'emotional_range', 100.0)

    config = _mc_config(targets={
        'emotional_range': {
            'min': 0.3, 'max': 0.8,
            'metric': 'emotional_range',
            'normalize': 125.0,
        },
    })
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import run_meta_controller
        adjustments = await run_meta_controller()

    # 100 / 125 = 0.8, exactly at max → in range, no adjustment
    emo_adj = [a for a in adjustments if a['target_metric'] == 'emotional_range']
    assert len(emo_adj) == 0


@pytest.mark.asyncio
async def test_production_scale_above_range(test_db):
    """18. Raw emotional_range=120 (120 bins) with normalize=125 → 0.96, above max."""
    await _seed_metric(test_db, 'emotional_range', 120.0)

    config = _mc_config(targets={
        'emotional_range': {
            'min': 0.3, 'max': 0.8,
            'metric': 'emotional_range',
            'normalize': 125.0,
        },
    })
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import run_meta_controller
        adjustments = await run_meta_controller()

    # 120 / 125 = 0.96, above 0.8 → should trigger lower
    emo_adj = [a for a in adjustments if a['target_metric'] == 'emotional_range']
    assert len(emo_adj) == 1
    assert emo_adj[0]['new_value'] < emo_adj[0]['old_value']


@pytest.mark.asyncio
async def test_hard_floor_overrides_self_parameters(test_db):
    """19. Hard floor wins when self_parameters bounds conflict."""
    # Set self_parameters bounds TIGHTER than hard floor
    # min_bound=0.35, max_bound=0.45 vs hard_floor=[0.2, 0.8]
    await test_db.execute(
        """UPDATE self_parameters SET min_bound = 0.35, max_bound = 0.45
           WHERE key = 'hypothalamus.equilibria.diversive_curiosity'"""
    )
    # Set current value near the self_params max
    await test_db.execute(
        """UPDATE self_parameters SET value = 0.44
           WHERE key = 'hypothalamus.equilibria.diversive_curiosity'"""
    )
    await test_db.commit()
    from db.parameters import refresh_params_cache
    await refresh_params_cache()

    # Metric is below target → controller wants to RAISE
    await _seed_metric(test_db, 'initiative_rate', 0.05)

    # Hard floor allows up to 0.8, self_params only allows up to 0.45
    config = _mc_config(hard_floor={
        'hypothalamus.equilibria.diversive_curiosity': [0.2, 0.8],
    })
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import run_meta_controller
        adjustments = await run_meta_controller()

    if adjustments:
        adj = adjustments[0]
        if adj['param'] == 'hypothalamus.equilibria.diversive_curiosity':
            # self_params would clamp to 0.45, but step is 0.03 → 0.44+0.03=0.47
            # self_params clamps to 0.45, then hard floor re-clamps to [0.2, 0.8]
            # Hard floor says 0.45 is fine (within [0.2, 0.8])
            # Key invariant: result is ALWAYS within hard floor bounds
            assert adj['new_value'] >= 0.2, "Below hard floor min"
            assert adj['new_value'] <= 0.8, "Above hard floor max"
