"""TASK-075: Circuit breaker unit tests.

Tests the ActionHealth state machine, failure reporting, cooldown
exponential backoff, fatigue perception injection, and error translation.
"""

import sys
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'engine'))

from pipeline.basal_ganglia import (
    ActionHealth, get_action_health, report_action_failure,
    report_action_success, get_blocked_actions, reset_circuit_breakers,
    _CB_THRESHOLD, _CB_BASE_COOLDOWN, _CB_MAX_COOLDOWN, _CB_MULTIPLIER,
)
from pipeline.body import translate_error_to_perception
from pipeline.sensorium import _build_fatigue_perception


@pytest.fixture(autouse=True)
def _clean_breakers():
    """Reset circuit breakers before each test."""
    reset_circuit_breakers()
    yield
    reset_circuit_breakers()


# ── Test 1: Opens after threshold ──

class TestOpensAfterThreshold:
    def test_opens_after_threshold(self):
        """3 consecutive failures → state=open."""
        health = ActionHealth()
        assert health.state == 'closed'

        for i in range(_CB_THRESHOLD - 1):
            health.record_failure()
            assert health.state == 'closed', f"Should stay closed after {i + 1} failures"

        health.record_failure()
        assert health.state == 'open'
        assert health.consecutive_failures == _CB_THRESHOLD

    def test_opens_after_threshold_via_report(self):
        """Same test through the report_action_failure API."""
        for _ in range(_CB_THRESHOLD):
            report_action_failure('read_content')
        health = get_action_health('read_content')
        assert health.state == 'open'


# ── Test 2: Success resets counter ──

class TestSuccessResetsCounter:
    def test_success_resets_counter(self):
        """2 failures + 1 success → consecutive=0, state=closed."""
        health = ActionHealth()
        health.record_failure()
        health.record_failure()
        assert health.consecutive_failures == 2
        assert health.state == 'closed'

        health.record_success()
        assert health.consecutive_failures == 0
        assert health.state == 'closed'

    def test_success_after_half_open_closes(self):
        """Success during half_open → back to closed."""
        health = ActionHealth()
        health.state = 'half_open'
        health.consecutive_failures = 3
        health.record_success()
        assert health.state == 'closed'
        assert health.consecutive_failures == 0
        assert health.cooldown_seconds == _CB_BASE_COOLDOWN


# ── Test 3: Cooldown exponential backoff ──

class TestCooldownExponentialBackoff:
    def test_cooldown_exponential_backoff(self):
        """Verify 300s → 600s → 1200s → ... → 3600s cap."""
        health = ActionHealth()

        # First trip: threshold failures → open
        for _ in range(_CB_THRESHOLD):
            health.record_failure()
        assert health.state == 'open'
        assert health.cooldown_seconds == _CB_BASE_COOLDOWN  # 300s

        # Simulate cooldown expiry → half_open → failure → re-open with doubled cooldown
        health.state = 'half_open'
        health.record_failure()
        assert health.state == 'open'
        assert health.cooldown_seconds == _CB_BASE_COOLDOWN * _CB_MULTIPLIER  # 600s

        # Another half_open failure
        health.state = 'half_open'
        health.record_failure()
        assert health.state == 'open'
        assert health.cooldown_seconds == _CB_BASE_COOLDOWN * _CB_MULTIPLIER ** 2  # 1200s

        # Keep going until cap
        health.state = 'half_open'
        health.record_failure()  # 2400s

        health.state = 'half_open'
        health.record_failure()  # would be 4800s, capped to 3600s
        assert health.cooldown_seconds == _CB_MAX_COOLDOWN


# ── Test 4: Half-open allows one attempt ──

class TestHalfOpenAllowsOneAttempt:
    def test_half_open_allows_one_attempt(self):
        """After cooldown expires, one attempt is permitted."""
        health = ActionHealth()
        # Open the circuit
        for _ in range(_CB_THRESHOLD):
            health.record_failure()
        assert health.state == 'open'

        # Set last_failure_time far enough in the past
        health.last_failure_time = clock_now_minus(health.cooldown_seconds + 1)

        # is_blocked should transition to half_open and return False
        assert not health.is_blocked()
        assert health.state == 'half_open'


# ── Test 5: Half-open failure reopens ──

class TestHalfOpenFailureReopens:
    def test_half_open_failure_reopens(self):
        """Failed half-open → back to open with longer cooldown."""
        health = ActionHealth()
        health.state = 'half_open'
        health.cooldown_seconds = _CB_BASE_COOLDOWN

        health.record_failure()

        assert health.state == 'open'
        assert health.cooldown_seconds == _CB_BASE_COOLDOWN * _CB_MULTIPLIER


# ── Test 6: All blocked forces idle ──

class TestAllBlockedForcesIdle:
    @pytest.mark.asyncio
    async def test_all_blocked_forces_idle(self):
        """All intended actions circuit-broken → returns idle intention."""
        from models.pipeline import ValidatedOutput, Intention, ActionRequest
        from models.state import DrivesState

        # Open circuit breakers for browse and write_journal
        for action in ['read_content', 'write_journal']:
            for _ in range(_CB_THRESHOLD):
                report_action_failure(action)

        # Build validated output with both actions as intentions
        validated = ValidatedOutput(
            internal_monologue='test',
            dialogue='',
            expression='neutral',
            body_state='still',
            gaze='middle_distance',
            intentions=[
                Intention(action='read_content', impulse=0.8),
                Intention(action='write_journal', impulse=0.6),
            ],
        )

        drives = DrivesState()
        from pipeline.basal_ganglia import select_actions
        with _mock_db_calls():
            motor_plan = await select_actions(validated, drives, context={})

        # Should have forced idle since both real actions were circuit-broken
        assert len(motor_plan.actions) >= 1
        assert motor_plan.actions[0].action == 'idle'
        assert motor_plan.actions[0].source == 'circuit_breaker'

        # Both original actions should be in suppressed
        suppressed_actions = {d.action for d in motor_plan.suppressed}
        assert 'read_content' in suppressed_actions
        assert 'write_journal' in suppressed_actions


# ── Test 7: Fatigue perception injected ──

class TestFatiguePerceptionInjected:
    def test_fatigue_perception_injected(self):
        """Blocked action produces sensorium perception."""
        perc = _build_fatigue_perception(['read_content'])
        assert perc is not None
        assert perc.p_type == 'action_fatigue'
        assert perc.features['is_fatigue'] is True
        assert perc.features['blocked_count'] == 1
        assert perc.salience == 0.6

    def test_no_fatigue_when_no_blocked(self):
        """No blocked actions → no fatigue perception."""
        perc = _build_fatigue_perception([])
        assert perc is None

    def test_fatigue_in_get_blocked_actions(self):
        """get_blocked_actions returns currently open breakers."""
        # Open circuit for one action
        for _ in range(_CB_THRESHOLD):
            report_action_failure('read_content')

        blocked = get_blocked_actions()
        assert 'read_content' in blocked

    def test_multiple_blocked_actions(self):
        """Multiple blocked actions included in perception."""
        perc = _build_fatigue_perception(['read_content', 'post_x'])
        assert perc is not None
        assert perc.features['blocked_count'] == 2


# ── Test 8: Error perception not raw ──

class TestErrorPerceptionNotRaw:
    def test_timeout_translated(self):
        """Timeout errors get character-aligned translation."""
        result = translate_error_to_perception('TimeoutError: connect timeout after 30s')
        assert 'timeout' not in result.lower()
        assert 'fatigue' in result.lower() or 'fizzled' in result.lower()

    def test_rate_limit_translated(self):
        """Rate limit errors get character-aligned translation."""
        result = translate_error_to_perception('HTTPError: 429 rate_limit exceeded')
        assert '429' not in result
        assert 'rate_limit' not in result
        assert 'overstimulated' in result.lower() or 'rest' in result.lower()

    def test_unknown_error_gets_fallback(self):
        """Unknown error types get a generic character-aligned fallback."""
        result = translate_error_to_perception('SomeBizarreError: xyz123')
        assert 'SomeBizarreError' not in result
        assert 'xyz123' not in result
        assert 'resistance' in result.lower() or "didn't work" in result.lower()

    def test_none_error_gets_fallback(self):
        """None error string gets fallback."""
        result = translate_error_to_perception(None)
        assert result  # non-empty
        assert 'None' not in result

    def test_connection_error_translated(self):
        """Connection errors get appropriate translation."""
        result = translate_error_to_perception('ConnectionError: failed to connect')
        assert 'ConnectionError' not in result
        assert 'disconnected' in result.lower() or 'unreachable' in result.lower()


# ── Helpers ──

def clock_now_minus(seconds: float) -> datetime:
    """Return a UTC datetime `seconds` in the past."""
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


from contextlib import contextmanager


@contextmanager
def _mock_db_calls():
    """Mock DB calls used by select_actions so tests run without a database."""
    with patch('pipeline.basal_ganglia.db') as mock_db:
        mock_db.get_inhibitions_for_action = AsyncMock(return_value=[])
        mock_db.get_room_state = AsyncMock(return_value=MagicMock(shop_status='open'))
        mock_db.get_cycles_since_last_journal = AsyncMock(return_value=10)
        mock_db.get_cycles_since_last_visitor = AsyncMock(return_value=5)
        yield mock_db
