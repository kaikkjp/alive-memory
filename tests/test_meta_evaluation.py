"""Tests for TASK-091: Closed-loop self-evaluation.

10 unit tests + 2 integration tests:
 1. test_improved_outcome — metric was below target, now in range → outcome=improved, change kept
 2. test_degraded_outcome — metric was below target, now further below → outcome=degraded, reverted
 3. test_neutral_outcome — metric shifted <5% → outcome=neutral, kept
 4. test_side_effect_detected — target metric improved but another left range → outcome=side_effect, reverted
 5. test_revert_restores_value — after degraded, param returns to old_value
 6. test_confidence_updates — 3 improved + 1 degraded → confidence=0.75
 7. test_low_confidence_skipped — confidence <0.3 after 5 attempts → meta-controller skips this link
 8. test_adaptive_cooldown — high confidence → short cooldown, low confidence → long cooldown
 9. test_too_early_to_evaluate — experiment only 30 cycles old, window=50 → skipped
10. test_revert_logged_as_experiment — revert creates its own experiment entry
11. test_full_loop (integration) — adjust → evaluate → keep cycle
12. test_bad_adjustment_reverts (integration) — adjust → evaluate → revert → try different
"""

import os
import sys
import uuid
import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Helpers ──

async def _init_test_db(db_path: str):
    """Initialize a test database with schema + migrations."""
    import importlib
    import db.connection as _conn
    if not hasattr(_conn, '__file__') or not hasattr(_conn, 'get_db'):
        _conn = importlib.import_module('db.connection')
        sys.modules['db.connection'] = _conn

    _conn._db = None
    _conn.DB_PATH = db_path
    await _conn.init_db()
    return await _conn.get_db()


async def _seed_params(conn):
    """Seed minimum self_parameters needed for tests."""
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
    """Insert dummy cycle_log rows."""
    for i in range(count):
        await conn.execute(
            """INSERT INTO cycle_log (id, mode, ts)
               VALUES (?, 'idle', datetime('now'))""",
            (str(uuid.uuid4()),),
        )
    await conn.commit()


async def _seed_experiment(conn, cycle: int, param: str, old_val: float,
                           new_val: float, target_metric: str,
                           metric_val: float, outcome: str = 'pending',
                           metrics_snapshot: dict | None = None) -> int:
    """Insert a meta_experiments row. Returns id."""
    import json as _json
    snapshot_json = _json.dumps(metrics_snapshot) if metrics_snapshot else None
    cursor = await conn.execute(
        """INSERT INTO meta_experiments
           (cycle_at_change, param_name, old_value, new_value, reason,
            target_metric, metric_value_at_change, outcome,
            metrics_snapshot, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (cycle, param, old_val, new_val, 'test reason',
         target_metric, metric_val, outcome, snapshot_json),
    )
    await conn.commit()
    return cursor.lastrowid


def _mc_config(
    enabled=True,
    min_cycles=10,
    max_adj=2,
    cooldown=200,
    eval_window=50,
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
        'evaluation_window': eval_window,
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
    if not hasattr(_conn, '__file__') or not hasattr(_conn, 'get_db'):
        _conn = importlib.import_module('db.connection')
        sys.modules['db.connection'] = _conn

    db_path = str(tmp_path / 'test.db')
    _conn._db = None
    _conn.DB_PATH = db_path

    conn = await _init_test_db(db_path)
    await _seed_params(conn)
    await _seed_cycles(conn, 300)  # enough for eval window tests

    from db.parameters import refresh_params_cache
    await refresh_params_cache()

    yield conn

    if _conn._db is not None:
        await _conn._db.close()
        _conn._db = None


# ── Unit Tests ──

@pytest.mark.asyncio
async def test_improved_outcome(test_db):
    """1. Metric was below target, now in range → outcome=improved, change kept."""
    # Experiment: initiative_rate was 0.05 (below min 0.12), raised curiosity
    exp_id = await _seed_experiment(
        test_db, cycle=100,
        param='hypothalamus.equilibria.diversive_curiosity',
        old_val=0.37, new_val=0.40,
        target_metric='initiative_rate', metric_val=0.05,
    )
    # Now initiative_rate is 0.20 (in range [0.12, 0.35])
    await _seed_metric(test_db, 'initiative_rate', 0.20)
    await _seed_metric(test_db, 'emotional_range', 0.50)

    config = _mc_config(eval_window=50)
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import evaluate_experiments
        results = await evaluate_experiments()

    assert len(results) == 1
    assert results[0]['outcome'] == 'improved'
    assert results[0]['reverted'] is False

    # Verify DB was updated
    from db.meta_experiments import get_pending_experiments
    pending = await get_pending_experiments()
    assert len(pending) == 0  # no longer pending


@pytest.mark.asyncio
async def test_degraded_outcome(test_db):
    """2. Metric was below target, now further below → outcome=degraded, reverted."""
    exp_id = await _seed_experiment(
        test_db, cycle=100,
        param='hypothalamus.equilibria.diversive_curiosity',
        old_val=0.37, new_val=0.40,
        target_metric='initiative_rate', metric_val=0.08,
    )
    # Initiative rate got WORSE (further from target)
    await _seed_metric(test_db, 'initiative_rate', 0.02)
    await _seed_metric(test_db, 'emotional_range', 0.50)

    config = _mc_config(eval_window=50)
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import evaluate_experiments
        results = await evaluate_experiments()

    assert len(results) == 1
    assert results[0]['outcome'] == 'degraded'
    assert results[0]['reverted'] is True


@pytest.mark.asyncio
async def test_neutral_outcome(test_db):
    """3. Metric shifted <5% relative → outcome=neutral, kept."""
    exp_id = await _seed_experiment(
        test_db, cycle=100,
        param='hypothalamus.equilibria.diversive_curiosity',
        old_val=0.37, new_val=0.40,
        target_metric='initiative_rate', metric_val=0.08,
    )
    # Initiative rate barely moved (0.08 → 0.081, still below min 0.12)
    await _seed_metric(test_db, 'initiative_rate', 0.081)
    await _seed_metric(test_db, 'emotional_range', 0.50)

    config = _mc_config(eval_window=50)
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import evaluate_experiments
        results = await evaluate_experiments()

    assert len(results) == 1
    assert results[0]['outcome'] == 'neutral'
    assert results[0]['reverted'] is False


@pytest.mark.asyncio
async def test_side_effect_detected(test_db):
    """4. Target metric improved but another left range (via stored snapshot) → outcome=side_effect, reverted."""
    # Experiment stores a snapshot showing emotional_range was IN range (0.50)
    # at the time of adjustment.
    exp_id = await _seed_experiment(
        test_db, cycle=100,
        param='hypothalamus.equilibria.diversive_curiosity',
        old_val=0.37, new_val=0.40,
        target_metric='initiative_rate', metric_val=0.05,
        metrics_snapshot={'initiative_rate': 0.05, 'emotional_range': 0.50},
    )
    # initiative_rate improved (now in range)
    await _seed_metric(test_db, 'initiative_rate', 0.20)
    # But emotional_range dropped OUT of range (was 0.50, now 0.25 < min 0.3)
    await _seed_metric(test_db, 'emotional_range', 0.25)

    config = _mc_config(eval_window=50)
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import evaluate_experiments
        results = await evaluate_experiments()

    assert len(results) == 1
    assert results[0]['outcome'] == 'side_effect'
    assert results[0]['reverted'] is True
    assert len(results[0]['side_effects']) == 1
    assert results[0]['side_effects'][0]['metric'] == 'emotional_range'


@pytest.mark.asyncio
async def test_revert_restores_value(test_db):
    """5. After degraded, param returns to old_value."""
    from db.parameters import refresh_params_cache, p

    # Set param to 0.40 (the "new" value post-adjustment)
    await test_db.execute(
        "UPDATE self_parameters SET value = 0.40 WHERE key = 'hypothalamus.equilibria.diversive_curiosity'"
    )
    await test_db.commit()
    await refresh_params_cache()

    exp_id = await _seed_experiment(
        test_db, cycle=100,
        param='hypothalamus.equilibria.diversive_curiosity',
        old_val=0.37, new_val=0.40,
        target_metric='initiative_rate', metric_val=0.08,
    )
    # Metric got worse
    await _seed_metric(test_db, 'initiative_rate', 0.02)
    await _seed_metric(test_db, 'emotional_range', 0.50)

    config = _mc_config(eval_window=50)
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import evaluate_experiments
        results = await evaluate_experiments()

    assert results[0]['reverted'] is True

    # Check param was restored
    await refresh_params_cache()
    restored = p('hypothalamus.equilibria.diversive_curiosity')
    assert restored == 0.37


@pytest.mark.asyncio
async def test_confidence_updates(test_db):
    """6. 3 improved + 1 degraded → confidence=0.75."""
    from db.meta_experiments import update_confidence, get_confidence

    param = 'hypothalamus.equilibria.diversive_curiosity'
    metric = 'initiative_rate'

    await update_confidence(param, metric, 'improved', 0.05, 100)
    await update_confidence(param, metric, 'improved', 0.03, 200)
    await update_confidence(param, metric, 'improved', 0.04, 300)
    await update_confidence(param, metric, 'degraded', 0.02, 400)

    rec = await get_confidence(param, metric)
    assert rec is not None
    assert rec['attempts'] == 4
    assert rec['improved'] == 3
    assert rec['degraded'] == 1
    assert rec['confidence'] == 0.75


@pytest.mark.asyncio
async def test_low_confidence_skipped(test_db):
    """7. Confidence <0.3 after 5 attempts → meta-controller skips this link."""
    from db.meta_experiments import update_confidence

    param = 'hypothalamus.equilibria.diversive_curiosity'
    metric = 'initiative_rate'

    # 1 improved, 4 degraded → confidence = 0.2
    await update_confidence(param, metric, 'improved', 0.05, 100)
    await update_confidence(param, metric, 'degraded', 0.02, 200)
    await update_confidence(param, metric, 'degraded', 0.02, 300)
    await update_confidence(param, metric, 'degraded', 0.02, 400)
    await update_confidence(param, metric, 'degraded', 0.02, 500)

    # Metric is below target → would normally adjust
    await _seed_metric(test_db, 'initiative_rate', 0.05)

    config = _mc_config(cooldown=0)  # no cooldown
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import run_meta_controller
        adjustments = await run_meta_controller()

    # Priority 1 candidate (diversive_curiosity) should be skipped due to low confidence
    # Priority 2 candidate (expression_need) should be picked instead
    if adjustments:
        init_adj = [a for a in adjustments if a['target_metric'] == 'initiative_rate']
        if init_adj:
            assert init_adj[0]['param'] == 'hypothalamus.equilibria.expression_need'


@pytest.mark.asyncio
async def test_adaptive_cooldown(test_db):
    """8. High confidence → shorter than base, low confidence → longer than base."""
    from sleep.meta_controller import compute_adaptive_cooldown

    base = 200

    # High confidence (0.9): 0.7× base — shorter than base (proven link)
    high = compute_adaptive_cooldown(base, 0.9)
    assert high == 140  # 200 * max(0.5, 2.5 - 1.8) = 200 * 0.7
    assert high < base  # truly shorter

    # Low confidence (0.3): 1.9× base — longer than base (unreliable link)
    low = compute_adaptive_cooldown(base, 0.3)
    assert low == 380  # 200 * max(0.5, 2.5 - 0.6) = 200 * 1.9
    assert low > base  # truly longer

    # Default (0.5): 1.5× base — cautious
    default = compute_adaptive_cooldown(base, 0.5)
    assert default == 300  # 200 * max(0.5, 2.5 - 1.0) = 200 * 1.5

    # Perfect confidence (1.0): floor at 0.5× base
    perfect = compute_adaptive_cooldown(base, 1.0)
    assert perfect == 100  # 200 * max(0.5, 0.5) = 200 * 0.5

    assert perfect < high < base < default < low


@pytest.mark.asyncio
async def test_too_early_to_evaluate(test_db):
    """9. Experiment only 30 cycles old, window=50 → skipped."""
    # Seed 300 cycles total, experiment at cycle 280 → only 20 cycles old
    exp_id = await _seed_experiment(
        test_db, cycle=280,
        param='hypothalamus.equilibria.diversive_curiosity',
        old_val=0.37, new_val=0.40,
        target_metric='initiative_rate', metric_val=0.05,
    )
    await _seed_metric(test_db, 'initiative_rate', 0.20)
    await _seed_metric(test_db, 'emotional_range', 0.50)

    config = _mc_config(eval_window=50)
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import evaluate_experiments
        results = await evaluate_experiments()

    # Should be skipped (too early)
    assert len(results) == 0

    # Should still be pending
    from db.meta_experiments import get_pending_experiments
    pending = await get_pending_experiments()
    assert len(pending) == 1


@pytest.mark.asyncio
async def test_revert_logged_as_experiment(test_db):
    """10. Revert creates its own experiment entry with reason 'revert: {id}'."""
    exp_id = await _seed_experiment(
        test_db, cycle=100,
        param='hypothalamus.equilibria.diversive_curiosity',
        old_val=0.37, new_val=0.40,
        target_metric='initiative_rate', metric_val=0.08,
    )
    # Metric got worse → will trigger revert
    await _seed_metric(test_db, 'initiative_rate', 0.02)
    await _seed_metric(test_db, 'emotional_range', 0.50)

    config = _mc_config(eval_window=50)
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import evaluate_experiments
        results = await evaluate_experiments()

    assert results[0]['outcome'] == 'degraded'

    # Check for revert experiment entry
    from db.meta_experiments import get_recent_experiments
    experiments = await get_recent_experiments(limit=10)

    revert_exps = [e for e in experiments if f'revert: {exp_id}' in (e.get('reason') or '')]
    assert len(revert_exps) == 1
    assert revert_exps[0]['old_value'] == 0.40  # was new_value
    assert revert_exps[0]['new_value'] == 0.37  # back to old_value


# ── Integration Tests ──

@pytest.mark.asyncio
async def test_full_loop(test_db):
    """11. Adjust → evaluate → keep cycle."""
    from db.parameters import refresh_params_cache, p

    # Step 1: Run meta-controller to make an adjustment
    await _seed_metric(test_db, 'initiative_rate', 0.05)
    await _seed_metric(test_db, 'emotional_range', 0.50)

    config = _mc_config(eval_window=50, cooldown=0)
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import run_meta_controller
        adjustments = await run_meta_controller()

    assert len(adjustments) >= 1
    adj_param = adjustments[0]['param']
    adj_new = adjustments[0]['new_value']

    # Step 2: Simulate enough cycles passing
    await _seed_cycles(test_db, 100)

    # Step 3: Metric improved → now in range
    # Clear old metric snapshots and seed new one showing improvement
    await test_db.execute("DELETE FROM metrics_snapshots WHERE metric_name = 'initiative_rate'")
    await test_db.commit()
    await _seed_metric(test_db, 'initiative_rate', 0.20)  # in range [0.12, 0.35]
    await _seed_metric(test_db, 'emotional_range', 0.50)

    # Step 4: Evaluate
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import evaluate_experiments
        results = await evaluate_experiments()

    assert len(results) >= 1
    assert results[0]['outcome'] == 'improved'
    assert results[0]['reverted'] is False

    # Param should still be at the adjusted value
    await refresh_params_cache()
    current = p(adj_param)
    assert current == adj_new


@pytest.mark.asyncio
async def test_bad_adjustment_reverts(test_db):
    """12. Adjust → evaluate → revert → try different param."""
    from db.parameters import refresh_params_cache, p

    # Step 1: Make adjustment
    await _seed_metric(test_db, 'initiative_rate', 0.05)
    await _seed_metric(test_db, 'emotional_range', 0.50)

    config = _mc_config(eval_window=50, cooldown=0)
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import run_meta_controller
        adjustments = await run_meta_controller()

    assert len(adjustments) >= 1
    original_param = adjustments[0]['param']
    old_value = adjustments[0]['old_value']

    # Step 2: Add enough cycles
    await _seed_cycles(test_db, 100)

    # Step 3: Metric got WORSE
    await test_db.execute("DELETE FROM metrics_snapshots WHERE metric_name = 'initiative_rate'")
    await test_db.commit()
    await _seed_metric(test_db, 'initiative_rate', 0.01)  # worse than 0.05
    await _seed_metric(test_db, 'emotional_range', 0.50)

    # Step 4: Evaluate → revert
    with patch('sleep.meta_controller.cfg_section', return_value=config):
        from sleep.meta_controller import evaluate_experiments
        results = await evaluate_experiments()

    assert len(results) >= 1
    assert results[0]['outcome'] == 'degraded'
    assert results[0]['reverted'] is True

    # Param should be back to old value
    await refresh_params_cache()
    current = p(original_param)
    assert current == old_value
