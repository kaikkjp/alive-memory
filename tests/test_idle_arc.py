"""Tests for TASK-100: Idle Arc — Natural Response to Low Stimulus."""

import unittest
from models.state import idle_phase, idle_cycle_multiplier


class TestIdlePhase(unittest.TestCase):
    """idle_phase maps consecutive idle count to phase."""

    def test_deepen_at_zero(self):
        self.assertEqual(idle_phase(0), 'DEEPEN')

    def test_deepen_at_20(self):
        self.assertEqual(idle_phase(20), 'DEEPEN')

    def test_wander_at_21(self):
        self.assertEqual(idle_phase(21), 'WANDER')

    def test_wander_at_40(self):
        self.assertEqual(idle_phase(40), 'WANDER')

    def test_still_at_41(self):
        self.assertEqual(idle_phase(41), 'STILL')

    def test_still_at_100(self):
        self.assertEqual(idle_phase(100), 'STILL')


class TestIdleCycleMultiplier(unittest.TestCase):
    """idle_cycle_multiplier returns interval multipliers."""

    def test_deepen_1x(self):
        self.assertEqual(idle_cycle_multiplier(10), 1.0)

    def test_wander_1x(self):
        self.assertEqual(idle_cycle_multiplier(30), 1.0)

    def test_still_early_2x(self):
        self.assertEqual(idle_cycle_multiplier(50), 2.0)

    def test_still_deep_4x(self):
        self.assertEqual(idle_cycle_multiplier(70), 4.0)

    def test_boundary_40_is_wander(self):
        self.assertEqual(idle_cycle_multiplier(40), 1.0)

    def test_boundary_41_is_still(self):
        self.assertEqual(idle_cycle_multiplier(41), 2.0)

    def test_boundary_60_is_still_early(self):
        self.assertEqual(idle_cycle_multiplier(60), 2.0)

    def test_boundary_61_is_still_deep(self):
        self.assertEqual(idle_cycle_multiplier(61), 4.0)


class TestPerceptionRingBuffer(unittest.TestCase):
    """Perception pool avoids repeats within 3 cycles."""

    def test_no_repeat_within_3(self):
        from pipeline.thalamus import _pick_solitude_perception, _recent_perceptions
        _recent_perceptions.clear()

        seen = []
        for _ in range(6):
            p = _pick_solitude_perception(has_physical=True)
            # Should not repeat any of the last 3
            if len(seen) >= 3:
                self.assertNotIn(p, seen[-3:],
                                 f"'{p}' repeated within last 3 picks")
            seen.append(p)

    def test_digital_pool_used(self):
        from pipeline.thalamus import (
            _pick_solitude_perception, _recent_perceptions,
            _DIGITAL_SOLITUDE_POOL,
        )
        _recent_perceptions.clear()

        p = _pick_solitude_perception(has_physical=False)
        self.assertIn(p, _DIGITAL_SOLITUDE_POOL)

    def test_physical_pool_used(self):
        from pipeline.thalamus import (
            _pick_solitude_perception, _recent_perceptions,
            _PHYSICAL_SOLITUDE_POOL,
        )
        _recent_perceptions.clear()

        p = _pick_solitude_perception(has_physical=True)
        self.assertIn(p, _PHYSICAL_SOLITUDE_POOL)


class TestArbiterWanderChannel(unittest.TestCase):
    """Wander channel activates in WANDER phase with high curiosity."""

    def test_wander_not_triggered_in_deepen(self):
        """idle_streak <= 20 should not trigger wander."""
        import asyncio
        from pipeline.arbiter import decide_cycle_focus
        from models.state import DrivesState

        drives = DrivesState(curiosity=0.8, rest_need=0.1, energy=0.8,
                             expression_need=0.1)
        state = {}
        focus = asyncio.run(decide_cycle_focus(drives, state, idle_streak=10))
        # Should be idle without wander payload
        if focus.payload:
            self.assertNotIn('wander_source', focus.payload)


if __name__ == '__main__':
    unittest.main()
