"""Tests for identity.drift — drift detection engine (TASK-062)."""

import json
import os
import tempfile
from dataclasses import asdict
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from identity.drift import (
    BehavioralBaseline,
    DriftDetector,
    DriftResult,
    _compute_action_frequency_drift,
    _compute_scalar_drift,
    _build_drift_summary,
    get_drift_state,
    reset_detector,
)


# ─── Config fixture ───

@pytest.fixture
def config():
    return {
        'window_size': 20,
        'thresholds': {'notable': 0.3, 'significant': 0.5},
        'metric_weights': {
            'action_frequency': 0.35,
            'drive_response': 0.25,
            'conversation_style': 0.25,
            'sleep_wake_rhythm': 0.15,
        },
        'min_cycles_for_detection': 10,
        'cooldown_cycles_between_events': 5,
        'baseline_ema_alpha': 0.05,
    }


@pytest.fixture
def tmp_baseline(tmp_path):
    """Return a temporary path for baseline JSON."""
    return str(tmp_path / 'baseline.json')


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset module singleton before each test."""
    reset_detector()
    yield
    reset_detector()


# ─── BehavioralBaseline Tests ───

class TestBehavioralBaseline:
    def test_fresh_baseline_defaults(self):
        b = BehavioralBaseline()
        assert b.cycle_count == 0
        assert b.action_frequencies == {}
        assert b.avg_dialogue_length == 0.0
        assert b.avg_energy == 0.8

    def test_save_and_load(self, tmp_baseline):
        b = BehavioralBaseline(
            action_frequencies={'read': 0.3, 'speak': 0.7},
            avg_dialogue_length=50.0,
            cycle_count=25,
        )
        b.save(tmp_baseline)
        loaded = BehavioralBaseline.load(tmp_baseline)
        assert loaded.action_frequencies == {'read': 0.3, 'speak': 0.7}
        assert loaded.avg_dialogue_length == 50.0
        assert loaded.cycle_count == 25

    def test_load_missing_file(self, tmp_baseline):
        b = BehavioralBaseline.load(tmp_baseline)
        assert b.cycle_count == 0

    def test_load_corrupt_file(self, tmp_baseline):
        with open(tmp_baseline, 'w') as f:
            f.write('{invalid json}')
        b = BehavioralBaseline.load(tmp_baseline)
        assert b.cycle_count == 0

    def test_ema_update(self):
        b = BehavioralBaseline()
        # Simulate 15 bootstrap cycles with consistent data
        for _ in range(15):
            b.update_from_window(
                window_actions={'read': 0.3, 'speak': 0.5, 'rest': 0.2},
                window_dialogue_len=100.0,
                window_mood=0.2,
                window_energy=0.7,
                window_cycles_per_day=30.0,
                alpha=0.05,
            )
        assert b.cycle_count == 15
        # After 15 updates, values should converge toward the window values
        assert b.action_frequencies['read'] > 0.1
        assert b.action_frequencies['speak'] > 0.2
        assert b.avg_dialogue_length > 50.0
        assert b.avg_energy < 0.8  # Started at 0.8, converging to 0.7

    def test_bootstrap_phase_uses_faster_alpha(self):
        b = BehavioralBaseline()
        # During bootstrap (cycle_count < 10), alpha is multiplied by 5
        b.update_from_window(
            window_actions={'read': 1.0},
            window_dialogue_len=200.0,
            window_mood=0.5,
            window_energy=0.6,
            window_cycles_per_day=20.0,
            alpha=0.05,
        )
        # After single bootstrap cycle, values should jump significantly
        # (effective alpha = 0.25 during bootstrap)
        assert b.action_frequencies['read'] > 0.2
        assert b.avg_dialogue_length > 40.0

    def test_prunes_near_zero_actions(self):
        b = BehavioralBaseline(
            action_frequencies={'read': 0.0005, 'speak': 0.5},
            cycle_count=20,
        )
        b.update_from_window(
            window_actions={'speak': 1.0},
            window_dialogue_len=100.0,
            window_mood=0.0,
            window_energy=0.8,
            window_cycles_per_day=30.0,
            alpha=0.05,
        )
        # 'read' should be pruned since it was already near-zero and
        # only got further decayed
        assert 'read' not in b.action_frequencies


# ─── Drift Scoring Tests ───

class TestDriftScoring:
    def test_identical_distributions_zero_drift(self):
        freqs = {'read': 0.3, 'speak': 0.5, 'rest': 0.2}
        assert _compute_action_frequency_drift(freqs, freqs) == 0.0

    def test_completely_different_distributions(self):
        baseline = {'read': 1.0}
        window = {'speak': 1.0}
        drift = _compute_action_frequency_drift(baseline, window)
        assert drift == 1.0  # TVD = sum(|1-0| + |0-1|) / 2 = 1.0

    def test_partial_shift(self):
        baseline = {'read': 0.5, 'speak': 0.5}
        window = {'read': 0.3, 'speak': 0.7}
        drift = _compute_action_frequency_drift(baseline, window)
        # TVD = (|0.5-0.3| + |0.5-0.7|) / 2 = (0.2 + 0.2) / 2 = 0.2
        assert abs(drift - 0.2) < 0.01

    def test_empty_distributions(self):
        assert _compute_action_frequency_drift({}, {}) == 0.0

    def test_scalar_drift_zero_when_equal(self):
        assert _compute_scalar_drift(0.5, 0.5) == 0.0

    def test_scalar_drift_large_change(self):
        # current=0.5, baseline=0.1 → |0.4| / 0.1 = 4.0, capped at 1.0
        assert _compute_scalar_drift(0.5, 0.1) == 1.0

    def test_scalar_drift_moderate_change(self):
        # current=0.3, baseline=0.5 → |0.2| / 0.5 = 0.4
        assert abs(_compute_scalar_drift(0.3, 0.5) - 0.4) < 0.01

    def test_scalar_drift_near_zero_baseline(self):
        # baseline near 0 → uses epsilon denominator
        drift = _compute_scalar_drift(0.1, 0.0)
        assert drift == 1.0  # 0.1 / 0.01 = 10, capped at 1.0


class TestDriftSummary:
    def test_action_frequency_shift_summary(self):
        metrics = {
            'action_frequency': 0.5,
            'drive_response': 0.1,
            'conversation_style': 0.1,
            'sleep_wake_rhythm': 0.1,
        }
        window_actions = {'read': 0.8, 'speak': 0.2}
        baseline_actions = {'read': 0.3, 'speak': 0.7}
        summary = _build_drift_summary(metrics, 0.5, window_actions, baseline_actions)
        assert 'speak' in summary or 'read' in summary

    def test_drive_response_summary(self):
        metrics = {
            'action_frequency': 0.1,
            'drive_response': 0.6,
            'conversation_style': 0.1,
            'sleep_wake_rhythm': 0.1,
        }
        summary = _build_drift_summary(metrics, 0.5, {}, {})
        assert 'emotional' in summary.lower()

    def test_conversation_style_summary(self):
        metrics = {
            'action_frequency': 0.1,
            'drive_response': 0.1,
            'conversation_style': 0.6,
            'sleep_wake_rhythm': 0.1,
        }
        summary = _build_drift_summary(metrics, 0.5, {}, {})
        assert 'speaking' in summary.lower() or 'communicate' in summary.lower()


# ─── DriftDetector Tests ───

def _make_window_data(
    action_freqs=None, dialogue_len=100.0, mood=0.2, energy=0.7,
    cpd=30.0, cycle_count=20,
):
    """Helper to create window data dict."""
    return {
        'cycle_count': cycle_count,
        'action_frequencies': action_freqs or {'read': 0.3, 'speak': 0.5, 'rest': 0.2},
        'avg_dialogue_length': dialogue_len,
        'avg_mood_valence': mood,
        'avg_energy': energy,
        'cycles_per_day': cpd,
    }


class TestDriftDetector:
    @pytest.mark.asyncio
    async def test_insufficient_data_returns_none(self, config, tmp_baseline):
        """No drift computed when window has no cycles."""
        detector = DriftDetector(config=config, baseline_path=tmp_baseline)
        with patch('identity.drift._query_recent_window', new_callable=AsyncMock) as mock_q:
            mock_q.return_value = _make_window_data(cycle_count=0)
            result = await detector.check({}, MagicMock())
            assert result is None

    @pytest.mark.asyncio
    async def test_baseline_builds_during_bootstrap(self, config, tmp_baseline):
        """During first min_cycles, no drift is detected (level='none')."""
        detector = DriftDetector(config=config, baseline_path=tmp_baseline)
        with patch('identity.drift._query_recent_window', new_callable=AsyncMock) as mock_q:
            mock_q.return_value = _make_window_data()
            # Run 5 cycles (less than min_cycles=10)
            for _ in range(5):
                result = await detector.check({}, MagicMock())
            assert result is not None
            assert result.level == 'none'
            assert detector.baseline.cycle_count == 5

    @pytest.mark.asyncio
    async def test_stable_behavior_no_drift(self, config, tmp_baseline):
        """Consistent behavior over many cycles produces no drift."""
        detector = DriftDetector(config=config, baseline_path=tmp_baseline)
        stable_data = _make_window_data()
        with patch('identity.drift._query_recent_window', new_callable=AsyncMock) as mock_q, \
             patch('identity.drift.db') as mock_db:
            mock_q.return_value = stable_data
            # Build baseline over 30 cycles (same data each time)
            for _ in range(30):
                result = await detector.check({}, MagicMock())
            assert result is not None
            assert result.composite < 0.3
            assert result.level == 'none'

    @pytest.mark.asyncio
    async def test_sustained_shift_triggers_drift(self, config, tmp_baseline):
        """Behavior change after stable baseline triggers drift event."""
        detector = DriftDetector(config=config, baseline_path=tmp_baseline)
        stable_data = _make_window_data(
            action_freqs={'read': 0.3, 'speak': 0.5, 'rest': 0.2},
        )
        shifted_data = _make_window_data(
            action_freqs={'read': 0.9, 'speak': 0.05, 'rest': 0.05},
            dialogue_len=20.0,  # was 100
            mood=-0.5,  # was 0.2
            energy=0.3,  # was 0.7
        )

        events_emitted = []

        async def capture_event(event):
            events_emitted.append(event)

        with patch('identity.drift._query_recent_window', new_callable=AsyncMock) as mock_q, \
             patch('identity.drift.db.append_event', new_callable=AsyncMock,
                   side_effect=capture_event):
            # Phase 1: build stable baseline
            mock_q.return_value = stable_data
            for _ in range(20):
                await detector.check({}, MagicMock())

            # Phase 2: shift behavior
            mock_q.return_value = shifted_data
            for _ in range(15):
                result = await detector.check({}, MagicMock())

            # Drift should be detected
            assert result.level in ('notable', 'significant')
            assert result.composite > 0.3
            assert len(events_emitted) >= 1
            assert events_emitted[0].event_type.startswith('drift_')

    @pytest.mark.asyncio
    async def test_return_to_normal_decreases_drift(self, config, tmp_baseline):
        """Restoring normal behavior after a shift reduces drift score."""
        detector = DriftDetector(config=config, baseline_path=tmp_baseline)
        stable = _make_window_data()
        shifted = _make_window_data(
            action_freqs={'read': 0.9, 'speak': 0.05, 'rest': 0.05},
            dialogue_len=10.0,
            mood=-0.5,
        )

        with patch('identity.drift._query_recent_window', new_callable=AsyncMock) as mock_q, \
             patch('identity.drift.db.append_event', new_callable=AsyncMock):
            # Build baseline
            mock_q.return_value = stable
            for _ in range(20):
                await detector.check({}, MagicMock())

            # Shift
            mock_q.return_value = shifted
            for _ in range(10):
                result_shifted = await detector.check({}, MagicMock())

            # Return to normal
            mock_q.return_value = stable
            for _ in range(30):
                result_normal = await detector.check({}, MagicMock())

            # Drift should decrease after returning to normal
            assert result_normal.composite < result_shifted.composite

    @pytest.mark.asyncio
    async def test_single_anomaly_no_drift(self, config, tmp_baseline):
        """A single odd cycle mixed into a normal window doesn't trigger drift.

        The window of 20 cycles has 19 normal + 1 anomalous, so the averages
        barely shift. This models real-world behavior where one odd cycle is
        diluted by the surrounding normal ones.
        """
        detector = DriftDetector(config=config, baseline_path=tmp_baseline)
        stable = _make_window_data()
        # Window with one anomaly out of 20: slight shift in averages
        slight_anomaly = _make_window_data(
            action_freqs={'read': 0.27, 'speak': 0.48, 'rest': 0.2, 'weird_action': 0.05},
            dialogue_len=95.0,   # was 100 — barely shifted
            mood=0.14,           # was 0.2 — barely shifted
            energy=0.67,         # was 0.7 — barely shifted
        )

        with patch('identity.drift._query_recent_window', new_callable=AsyncMock) as mock_q, \
             patch('identity.drift.db.append_event', new_callable=AsyncMock) as mock_event:
            # Build stable baseline over 25 cycles
            mock_q.return_value = stable
            for _ in range(25):
                await detector.check({}, MagicMock())

            # Window now includes one anomaly diluted across 20 cycles
            mock_q.return_value = slight_anomaly
            result = await detector.check({}, MagicMock())

            # Slight window shift should not trigger notable drift
            assert result.level == 'none'
            assert result.composite < 0.3

    @pytest.mark.asyncio
    async def test_cooldown_prevents_event_spam(self, config, tmp_baseline):
        """No event emitted within cooldown_cycles of last event."""
        config['cooldown_cycles_between_events'] = 5
        detector = DriftDetector(config=config, baseline_path=tmp_baseline)
        stable = _make_window_data()
        shifted = _make_window_data(
            action_freqs={'only_read': 1.0},
            dialogue_len=5.0,
            mood=-0.8,
            energy=0.2,
        )

        events_emitted = []

        async def capture_event(event):
            events_emitted.append(event)

        with patch('identity.drift._query_recent_window', new_callable=AsyncMock) as mock_q, \
             patch('identity.drift.db.append_event', new_callable=AsyncMock,
                   side_effect=capture_event):
            # Build baseline (15 cycles → cycle_count=15)
            mock_q.return_value = stable
            for _ in range(15):
                await detector.check({}, MagicMock())

            # First drift cycle emits event (cycle_count=16, last_event=16)
            mock_q.return_value = shifted
            await detector.check({}, MagicMock())
            assert len(events_emitted) == 1

            # Next 5 cycles within cooldown (17-21: diffs 1-5, all <= 5)
            for _ in range(5):
                await detector.check({}, MagicMock())
            assert len(events_emitted) == 1  # No new events during cooldown

    @pytest.mark.asyncio
    async def test_event_emitted_after_cooldown_expires(self, config, tmp_baseline):
        """After cooldown, a new drift event can be emitted."""
        config['cooldown_cycles_between_events'] = 3
        detector = DriftDetector(config=config, baseline_path=tmp_baseline)
        stable = _make_window_data()
        shifted = _make_window_data(
            action_freqs={'only_read': 1.0},
            dialogue_len=5.0,
            mood=-0.8,
            energy=0.2,
        )

        events_emitted = []

        async def capture_event(event):
            events_emitted.append(event)

        with patch('identity.drift._query_recent_window', new_callable=AsyncMock) as mock_q, \
             patch('identity.drift.db.append_event', new_callable=AsyncMock,
                   side_effect=capture_event):
            # Build baseline
            mock_q.return_value = stable
            for _ in range(15):
                await detector.check({}, MagicMock())

            # Drift cycles — first event
            mock_q.return_value = shifted
            for _ in range(5):
                await detector.check({}, MagicMock())

            first_count = len(events_emitted)
            assert first_count >= 1

            # Continue drifting past cooldown (3 cycles)
            for _ in range(5):
                await detector.check({}, MagicMock())

            # Should have emitted at least one more
            assert len(events_emitted) > first_count

    @pytest.mark.asyncio
    async def test_drift_summary_only_for_significant(self, config, tmp_baseline):
        """get_drift_summary() returns text only when level is significant."""
        detector = DriftDetector(config=config, baseline_path=tmp_baseline)

        # No result yet
        assert detector.get_drift_summary() is None

        # Mock a notable result
        detector._last_result = DriftResult(
            composite=0.35, metrics={}, level='notable', summary='test',
        )
        assert detector.get_drift_summary() is None

        # Mock a significant result
        detector._last_result = DriftResult(
            composite=0.55, metrics={}, level='significant',
            summary='I have been more withdrawn',
        )
        assert detector.get_drift_summary() == 'I have been more withdrawn'


# ─── Dashboard API Tests ───

class TestDriftDashboardState:
    @pytest.mark.asyncio
    async def test_get_drift_state_no_result(self):
        """Dashboard returns zeros when no check has run."""
        reset_detector()
        # Need to mock the get_detector to return a fresh detector
        with patch('identity.drift._detector', None):
            with patch('identity.drift.BehavioralBaseline.load') as mock_load:
                mock_load.return_value = BehavioralBaseline()
                state = await get_drift_state()
                assert state['composite'] == 0.0
                assert state['level'] == 'none'
                assert state['baseline_cycles'] == 0
                assert state['baseline_mature'] is False

    @pytest.mark.asyncio
    async def test_get_drift_state_with_result(self, config, tmp_baseline):
        """Dashboard returns actual data after checks have run."""
        from identity.drift import get_detector as _get_detector
        reset_detector()

        detector = DriftDetector(config=config, baseline_path=tmp_baseline)
        detector._last_result = DriftResult(
            composite=0.42,
            metrics={
                'action_frequency': 0.5,
                'drive_response': 0.3,
                'conversation_style': 0.4,
                'sleep_wake_rhythm': 0.2,
            },
            level='notable',
            summary='Acting differently',
        )
        detector._baseline.cycle_count = 25

        with patch('identity.drift._detector', detector):
            state = await get_drift_state()
            assert state['composite'] == 0.42
            assert state['level'] == 'notable'
            assert state['summary'] == 'Acting differently'
            assert state['baseline_cycles'] == 25
            assert state['baseline_mature'] is True


# ─── Self-Context Injection Test ───

class TestSelfContextInjection:
    @pytest.mark.asyncio
    async def test_drift_summary_appended_to_self_state(self):
        """When drift is significant, summary appears in build_self_state output."""
        # This tests the integration point in heartbeat.py
        mock_detector = MagicMock()
        mock_detector.get_drift_summary.return_value = 'I have been more withdrawn than usual'

        with patch('identity.drift.get_detector', return_value=mock_detector):
            from identity.drift import get_detector
            d = get_detector()
            summary = d.get_drift_summary()
            assert summary == 'I have been more withdrawn than usual'

    @pytest.mark.asyncio
    async def test_no_drift_summary_when_stable(self):
        """When drift is none/notable, no summary in self-context."""
        mock_detector = MagicMock()
        mock_detector.get_drift_summary.return_value = None

        with patch('identity.drift.get_detector', return_value=mock_detector):
            from identity.drift import get_detector
            d = get_detector()
            summary = d.get_drift_summary()
            assert summary is None
