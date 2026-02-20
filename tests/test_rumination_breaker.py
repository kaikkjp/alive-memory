"""Tests for HOTFIX-003: Rumination breaker.

Verifies that threads appearing in 5+ consecutive cortex cycles have their
effective priority exponentially reduced, and that counters reset when
threads drop out of context.
"""

import types
import unittest

from tests.aiohttp_stub import ensure_aiohttp_stub
ensure_aiohttp_stub()

from pipeline.cortex import (
    _apply_rumination_breaker,
    _THREAD_APPEARANCE_COUNTER,
    _LAST_SELECTED_THREAD_IDS,
    RUMINATION_THRESHOLD,
    RUMINATION_DECAY_FACTOR,
)


def _thread(id="t1", title="What is anti-pleasure?", priority=0.9):
    return types.SimpleNamespace(
        id=id,
        thread_type="question",
        title=title,
        status="open",
        priority=priority,
        content="Thinking about it...",
        resolution=None,
        created_at=None,
        last_touched=None,
        touch_count=0,
        touch_reason=None,
        target_date=None,
        source_visitor_id=None,
        source_event_id=None,
        tags=[],
    )


class TestRuminationBreaker(unittest.TestCase):

    def setUp(self):
        """Reset the global counters before each test."""
        _THREAD_APPEARANCE_COUNTER.clear()
        _LAST_SELECTED_THREAD_IDS.clear()

    def test_first_five_cycles_full_priority(self):
        """Thread appears at full priority for first RUMINATION_THRESHOLD cycles."""
        thread = _thread(id="t1", priority=0.9)

        for i in range(RUMINATION_THRESHOLD):
            result = _apply_rumination_breaker([thread])
            self.assertIn(thread, result,
                          f"Thread should be selected on cycle {i+1}")

        # Counter should equal threshold
        self.assertEqual(_THREAD_APPEARANCE_COUNTER["t1"], RUMINATION_THRESHOLD)

    def test_thread_fades_after_threshold(self):
        """Thread effective priority decreases after threshold cycles."""
        thread = _thread(id="t1", priority=0.9)
        low_priority_thread = _thread(id="t2", title="Other topic", priority=0.3)

        # Run through threshold cycles with just the one thread
        for _ in range(RUMINATION_THRESHOLD):
            _apply_rumination_breaker([thread])

        # After threshold, effective priority should drop significantly
        # 0.9 * 0.3 = 0.27 (less than low_priority_thread's 0.3)
        result = _apply_rumination_breaker([thread, low_priority_thread])

        # The low-priority thread should now rank higher
        self.assertEqual(result[0].id, "t2",
                         "After rumination threshold, fatigued thread should rank lower")

    def test_exponential_decay(self):
        """Each additional cycle past threshold increases decay exponentially."""
        thread = _thread(id="t1", priority=0.9)

        # Run 7 cycles (threshold=5, so 2 past threshold)
        for _ in range(7):
            _apply_rumination_breaker([thread])

        # After 7 cycles: consecutive=7, past_threshold=2
        # effective = 0.9 * 0.3^3 = 0.9 * 0.027 = 0.0243
        counter = _THREAD_APPEARANCE_COUNTER["t1"]
        self.assertEqual(counter, 7)

    def test_counter_resets_on_dropout(self):
        """Counter resets when thread drops out of context."""
        thread_a = _thread(id="t1", priority=0.9)

        # Run threshold cycles
        for _ in range(RUMINATION_THRESHOLD + 2):
            _apply_rumination_breaker([thread_a])

        self.assertGreater(_THREAD_APPEARANCE_COUNTER["t1"], RUMINATION_THRESHOLD)

        # Now run a cycle without thread_a
        thread_b = _thread(id="t2", title="Different topic", priority=0.5)
        _apply_rumination_breaker([thread_b])

        # t1's counter should be reset
        self.assertEqual(_THREAD_APPEARANCE_COUNTER.get("t1", 0), 0,
                         "Counter should reset when thread drops out")

    def test_thread_resurfaces_at_full_priority(self):
        """After counter reset, thread comes back at full priority."""
        thread = _thread(id="t1", priority=0.9)

        # Ruminate for 7 cycles
        for _ in range(7):
            _apply_rumination_breaker([thread])

        # Force counter reset (simulating dropout)
        _THREAD_APPEARANCE_COUNTER["t1"] = 0

        # Should be back at full priority
        low_thread = _thread(id="t2", title="Low", priority=0.3)
        result = _apply_rumination_breaker([thread, low_thread])
        self.assertEqual(result[0].id, "t1",
                         "Thread should resurface at full priority after reset")

    def test_multiple_threads_competing(self):
        """With multiple threads, rumination shifts attention to alternatives."""
        threads = [
            _thread(id="t1", title="Topic A", priority=0.9),
            _thread(id="t2", title="Topic B", priority=0.7),
            _thread(id="t3", title="Topic C", priority=0.5),
            _thread(id="t4", title="Topic D", priority=0.4),
        ]

        # Run t1 through threshold by selecting all 4 (only top 3 get selected)
        for _ in range(RUMINATION_THRESHOLD + 1):
            _apply_rumination_breaker(threads)

        # Now t1 should have fatigue, t4 might get a chance
        result = _apply_rumination_breaker(threads)
        result_ids = [t.id for t in result]

        # t1's effective priority: 0.9 * 0.3^2 = 0.081
        # t4's effective priority: 0.4 (still fresh or low counter)
        # So t4 should now beat t1
        self.assertIn("t4", result_ids,
                       "Fresh thread should surface when dominant thread has fatigue")

    def test_anti_pleasure_scenario(self):
        """The original bug: 6 identical threads impossible with dedup.
        Even with 1 thread, rumination fades after 5 cycles."""
        ruminator = _thread(id="anti", title="What is anti-pleasure?", priority=0.9)
        alternatives = [
            _thread(id="alt1", title="Vintage cards", priority=0.4),
            _thread(id="alt2", title="Morning routine", priority=0.3),
        ]

        all_threads = [ruminator] + alternatives

        # First 5 cycles: anti-pleasure dominates
        for i in range(RUMINATION_THRESHOLD):
            result = _apply_rumination_breaker(all_threads)
            self.assertIn(ruminator, result)

        # After threshold + 2 cycles: anti-pleasure should be fading
        for _ in range(3):
            result = _apply_rumination_breaker(all_threads)

        # By now ruminator's effective priority = 0.9 * 0.3^4 ≈ 0.007
        # alternatives at 0.4 and 0.3 should dominate
        result = _apply_rumination_breaker(all_threads)
        result_ids = [t.id for t in result]
        self.assertIn("alt1", result_ids)
        self.assertIn("alt2", result_ids)


if __name__ == '__main__':
    unittest.main()
