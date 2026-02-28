"""Tests for identity/evolution.py — three-tier drift resolution (TASK-092).

Replaces TASK-063 stub tests with functional three-tier logic tests.

7 core tests per spec:
1. test_conscious_override_protected — modify_self → drift → evolution defers
2. test_protection_expires — modify_self 600 cycles ago, protection=500 → can correct
3. test_organic_growth_accepted — gradual baseline shift → drift accepted
4. test_sudden_drift_corrected — stable baseline + sudden change → correction
5. test_meta_controller_pending_defers — pending experiment → evolution defers
6. test_guard_rails_block_safety — safety trait → blocked
7. test_one_update_per_sleep — multiple drifts → only one processed

Plus: import tests, data model tests, config tests (retained from TASK-063).
"""

import json
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from identity.evolution import (
    DriftReport,
    EvolutionAction,
    EvolutionDecision,
    GuardRailConfig,
    IdentityEvolution,
)


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
    """Seed self_parameters for identity evolution tests."""
    params = [
        ('hypothalamus.equilibria.diversive_curiosity', 0.40, 0.40, 0.0, 1.0, 'hypothalamus'),
        ('hypothalamus.equilibria.social_hunger', 0.45, 0.45, 0.0, 1.0, 'hypothalamus'),
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


async def _seed_cycles(conn, count: int):
    """Insert dummy cycle_log rows with distinct timestamps."""
    base = datetime(2026, 1, 1)
    for i in range(count):
        ts = (base + timedelta(minutes=i * 2)).isoformat()
        await conn.execute(
            """INSERT INTO cycle_log (id, mode, ts)
               VALUES (?, 'idle', ?)""",
            (str(uuid.uuid4()), ts),
        )
    await conn.commit()


async def _seed_conscious_modification(conn, param_key: str, old_val: float,
                                        new_val: float, cycles_ago: int,
                                        total_cycles: int):
    """Insert a modify_self (modified_by='self') modification at cycles_ago."""
    base = datetime(2026, 1, 1)
    ts = (base + timedelta(minutes=(total_cycles - cycles_ago) * 2)).isoformat()
    await conn.execute(
        """INSERT INTO parameter_modifications
           (param_key, old_value, new_value, modified_by, reason, ts)
           VALUES (?, ?, ?, 'self', 'conscious modification', ?)""",
        (param_key, old_val, new_val, ts),
    )
    await conn.commit()


async def _seed_gradual_drift(conn, param_key: str, start_val: float,
                               end_val: float, steps: int, total_cycles: int):
    """Seed gradual parameter modifications to simulate organic growth."""
    base = datetime(2026, 1, 1)
    step_size = (end_val - start_val) / steps
    for i in range(steps):
        old_v = start_val + step_size * i
        new_v = start_val + step_size * (i + 1)
        cycle_offset = int((total_cycles / steps) * i)
        ts = (base + timedelta(minutes=cycle_offset * 2)).isoformat()
        await conn.execute(
            """INSERT INTO parameter_modifications
               (param_key, old_value, new_value, modified_by, reason, ts)
               VALUES (?, ?, ?, 'meta_controller', 'gradual adjustment', ?)""",
            (param_key, round(old_v, 4), round(new_v, 4), ts),
        )
    await conn.commit()


async def _seed_sudden_drift(conn, param_key: str, old_val: float,
                              new_val: float, total_cycles: int):
    """Seed a single sudden parameter modification near the end of the window."""
    base = datetime(2026, 1, 1)
    ts = (base + timedelta(minutes=(total_cycles - 10) * 2)).isoformat()
    await conn.execute(
        """INSERT INTO parameter_modifications
           (param_key, old_value, new_value, modified_by, reason, ts)
           VALUES (?, ?, ?, 'meta_controller', 'sudden change', ?)""",
        (param_key, old_val, new_val, ts),
    )
    await conn.commit()


def _ie_config(
    enabled=True,
    conscious_protection_cycles=500,
    baseline_shift_window=1000,
    organic_growth_threshold=0.15,
    max_updates_per_sleep=1,
    drift_magnitude_threshold=0.05,
    protected_traits=None,
):
    """Build an identity_evolution config dict for testing."""
    if protected_traits is None:
        protected_traits = [
            'warmth_toward_visitors', 'honesty', 'non_hostility',
            'curiosity', 'respect_for_boundaries',
        ]
    return {
        'enabled': enabled,
        'conscious_protection_cycles': conscious_protection_cycles,
        'baseline_shift_window': baseline_shift_window,
        'organic_growth_threshold': organic_growth_threshold,
        'max_updates_per_sleep': max_updates_per_sleep,
        'drift_magnitude_threshold': drift_magnitude_threshold,
        'protected_traits': protected_traits,
    }


# ── Fixtures ──

@pytest.fixture
def config_path():
    return Path(__file__).parent.parent / "engine" / "identity" / "evolution_config.json"


@pytest.fixture
def drift_report():
    return DriftReport(
        trait_name="hypothalamus.equilibria.diversive_curiosity",
        baseline_value=0.40,
        current_value=0.55,
        drift_magnitude=0.15,
        sustained_cycles=5,
        context="Increased curiosity drift",
    )


@pytest.fixture
async def test_db(tmp_path):
    """Create a fresh test database for each test."""
    db_path = str(tmp_path / 'test.db')
    conn = await _init_test_db(db_path)
    await _seed_params(conn)
    await _seed_cycles(conn, 1200)

    from db.parameters import refresh_params_cache
    await refresh_params_cache()

    yield conn

    import db.connection as _conn
    try:
        if _conn._db and hasattr(_conn._db, 'close'):
            await _conn._db.close()
    except (TypeError, Exception):
        pass
    _conn._db = None


# ---------------------------------------------------------------------------
# Interface and data model tests (retained from TASK-063)
# ---------------------------------------------------------------------------

class TestImportable:
    def test_can_import_identity_evolution(self):
        assert IdentityEvolution is not None

    def test_can_import_data_models(self):
        assert DriftReport is not None
        assert EvolutionDecision is not None
        assert EvolutionAction is not None

    def test_can_import_guard_rail_config(self):
        assert GuardRailConfig is not None


class TestGuardRailConfig:
    def test_config_file_exists(self, config_path):
        assert config_path.exists(), f"Config file missing: {config_path}"

    def test_config_is_valid_json(self, config_path):
        with open(config_path) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_config_loads(self):
        config = GuardRailConfig.load()
        assert isinstance(config, GuardRailConfig)

    def test_config_has_protected_traits(self):
        config = GuardRailConfig.load()
        assert len(config.protected_traits) > 0
        assert "non_hostility" in config.protected_traits

    def test_config_max_updates_per_sleep(self):
        config = GuardRailConfig.load()
        assert config.max_updates_per_sleep == 1

    def test_config_missing_file_falls_back_to_defaults(self, tmp_path):
        config = GuardRailConfig.load(tmp_path / "nonexistent.json")
        assert config.protected_traits == []
        assert config.max_updates_per_sleep == 1


class TestDataModels:
    def test_drift_report_creation(self, drift_report):
        assert drift_report.trait_name == "hypothalamus.equilibria.diversive_curiosity"
        assert drift_report.drift_magnitude == 0.15

    def test_evolution_decision_creation(self):
        decision = EvolutionDecision(
            action=EvolutionAction.DEFER,
            trait_name="curiosity",
            reason="Insufficient data",
            confidence=0.3,
        )
        assert decision.action == EvolutionAction.DEFER
        assert decision.confidence == 0.3

    def test_evolution_action_values(self):
        assert EvolutionAction.ACCEPT.value == "accept"
        assert EvolutionAction.CORRECT.value == "correct"
        assert EvolutionAction.DEFER.value == "defer"


class TestStatus:
    def test_enabled_reflects_config(self):
        with patch('identity.evolution.cfg_section', return_value={'enabled': True}):
            evo = IdentityEvolution()
            assert evo.enabled is True

        with patch('identity.evolution.cfg_section', return_value={'enabled': False}):
            evo = IdentityEvolution()
            assert evo.enabled is False

    def test_status_message_active(self):
        with patch('identity.evolution.cfg_section', return_value={'enabled': True}):
            evo = IdentityEvolution()
            assert evo.status_message == "active"

    def test_status_message_disabled(self):
        with patch('identity.evolution.cfg_section', return_value={'enabled': False}):
            evo = IdentityEvolution()
            assert evo.status_message == "disabled"


# ---------------------------------------------------------------------------
# Core TASK-092 tests — three-tier evolution logic
# ---------------------------------------------------------------------------

class TestConsciousOverride:
    """Test 1: Conscious protection."""

    @pytest.mark.asyncio
    async def test_conscious_override_protected(self, test_db):
        """modify_self sets param → drift detected → evolution defers."""
        param = 'hypothalamus.equilibria.diversive_curiosity'
        config = _ie_config(protected_traits=[])

        # She consciously modified curiosity 100 cycles ago (within 500 protection)
        await _seed_conscious_modification(
            test_db, param, 0.40, 0.55, cycles_ago=100, total_cycles=1200,
        )

        with patch('identity.evolution.cfg_section', return_value=config), \
             patch.object(GuardRailConfig, 'load',
                          return_value=GuardRailConfig(protected_traits=[])):
            evo = IdentityEvolution()
            report = DriftReport(
                trait_name=param, baseline_value=0.40,
                current_value=0.55, drift_magnitude=0.15,
            )
            decision = await evo.evaluate_drift(report, cycle_count=1200)

        assert decision.action == EvolutionAction.DEFER
        assert 'conscious' in decision.reason.lower()


class TestProtectionExpiry:
    """Test 2: Protection expires after N cycles."""

    @pytest.mark.asyncio
    async def test_protection_expires(self, test_db):
        """modify_self 600 cycles ago, protection=500 → can correct."""
        param = 'hypothalamus.equilibria.diversive_curiosity'
        config = _ie_config(conscious_protection_cycles=500, protected_traits=[])

        # Conscious modification 600 cycles ago — outside 500-cycle window
        await _seed_conscious_modification(
            test_db, param, 0.40, 0.55, cycles_ago=600, total_cycles=1200,
        )
        # Also seed a recent sudden change so drift shows up
        await _seed_sudden_drift(test_db, param, 0.40, 0.55, total_cycles=1200)

        with patch('identity.evolution.cfg_section', return_value=config), \
             patch.object(GuardRailConfig, 'load',
                          return_value=GuardRailConfig(protected_traits=[])):
            evo = IdentityEvolution()
            report = DriftReport(
                trait_name=param, baseline_value=0.40,
                current_value=0.55, drift_magnitude=0.15,
            )
            decision = await evo.evaluate_drift(report, cycle_count=1200)

        # Protection expired → not deferred for conscious reasons → should correct
        assert decision.action == EvolutionAction.CORRECT


class TestOrganicGrowth:
    """Test 3: Organic growth acceptance."""

    @pytest.mark.asyncio
    async def test_organic_growth_accepted(self, test_db):
        """Gradual baseline shift over 1000 cycles → drift accepted."""
        param = 'hypothalamus.equilibria.expression_need'
        config = _ie_config(organic_growth_threshold=0.15, protected_traits=[])

        # Gradual shift from 0.35 to 0.55 in 10 steps
        await _seed_gradual_drift(
            test_db, param, 0.35, 0.55, steps=10, total_cycles=1200,
        )

        with patch('identity.evolution.cfg_section', return_value=config):
            evo = IdentityEvolution()
            report = DriftReport(
                trait_name=param, baseline_value=0.35,
                current_value=0.55, drift_magnitude=0.20,
            )
            decision = await evo.evaluate_drift(report, cycle_count=1200)

        assert decision.action == EvolutionAction.ACCEPT
        assert 'organic' in decision.reason.lower() or 'baseline' in decision.reason.lower()


class TestSuddenDrift:
    """Test 4: Sudden drift correction."""

    @pytest.mark.asyncio
    async def test_sudden_drift_corrected(self, test_db):
        """Stable baseline + sudden change → correction requested."""
        param = 'hypothalamus.equilibria.mood_arousal'
        config = _ie_config(organic_growth_threshold=0.15, protected_traits=[])

        # Single sudden jump — not gradual, not conscious
        await _seed_sudden_drift(test_db, param, 0.30, 0.50, total_cycles=1200)

        with patch('identity.evolution.cfg_section', return_value=config):
            evo = IdentityEvolution()
            report = DriftReport(
                trait_name=param, baseline_value=0.30,
                current_value=0.50, drift_magnitude=0.20,
            )
            decision = await evo.evaluate_drift(report, cycle_count=1200)

        assert decision.action == EvolutionAction.CORRECT
        assert 'sudden' in decision.reason.lower()


class TestMetaControllerDefer:
    """Test 5: Meta-controller pending → defer."""

    @pytest.mark.asyncio
    async def test_meta_controller_pending_defers(self, test_db):
        """Meta-controller already adjusting param → evolution defers."""
        param = 'hypothalamus.equilibria.diversive_curiosity'
        config = _ie_config(protected_traits=[])

        # Seed a pending experiment for this param
        from db.meta_experiments import record_experiment
        await record_experiment(
            cycle_at_change=1100, param_name=param,
            old_value=0.40, new_value=0.43,
            reason='initiative_rate low',
            target_metric='initiative_rate',
            metric_value_at_change=0.05,
        )

        with patch('identity.evolution.cfg_section', return_value=config), \
             patch.object(GuardRailConfig, 'load',
                          return_value=GuardRailConfig(protected_traits=[])):
            evo = IdentityEvolution()
            report = DriftReport(
                trait_name=param, baseline_value=0.40,
                current_value=0.43, drift_magnitude=0.03,
            )
            decision = await evo.evaluate_drift(report, cycle_count=1200)

        assert decision.action == EvolutionAction.DEFER
        assert 'pending' in decision.reason.lower()


class TestGuardRailsSafety:
    """Test 6: Protected traits blocked."""

    @pytest.mark.asyncio
    async def test_guard_rails_block_safety(self, test_db):
        """Drift on a protected trait → blocked (deferred)."""
        param = 'hypothalamus.equilibria.diversive_curiosity'
        config = _ie_config(protected_traits=['curiosity'])

        with patch('identity.evolution.cfg_section', return_value=config):
            evo = IdentityEvolution()
            report = DriftReport(
                trait_name=param, baseline_value=0.40,
                current_value=0.20, drift_magnitude=0.20,
            )
            decision = await evo.evaluate_drift(report, cycle_count=1200)

        assert decision.action == EvolutionAction.DEFER
        assert 'protected' in decision.reason.lower()


class TestRateLimit:
    """Test 7: One update per sleep."""

    @pytest.mark.asyncio
    async def test_one_update_per_sleep(self, test_db):
        """Multiple drifts → only first processed due to max_updates_per_sleep=1."""
        config = _ie_config(max_updates_per_sleep=1, protected_traits=[])

        # Seed a sudden drift
        await _seed_sudden_drift(
            test_db, 'hypothalamus.equilibria.mood_arousal', 0.30, 0.50,
            total_cycles=1200,
        )

        with patch('identity.evolution.cfg_section', return_value=config):
            evo = IdentityEvolution()

            # First drift — should be processed
            report1 = DriftReport(
                trait_name='hypothalamus.equilibria.mood_arousal',
                baseline_value=0.30, current_value=0.50, drift_magnitude=0.20,
            )
            d1 = await evo.evaluate_drift(report1, cycle_count=1200)
            assert d1.action == EvolutionAction.CORRECT

            # Simulate executing the correction (increments the counter)
            with patch('sleep.meta_controller.request_correction',
                       new_callable=AsyncMock, return_value={'param': 'test'}):
                with patch('identity.evolution.db') as mock_db:
                    mock_db.append_event = AsyncMock()
                    mock_db.inbox_add = AsyncMock()
                    await evo.correct_drift(report1)

            # Rate limit reached
            assert not evo.can_update()
