"""Tests for sim.clock — SimulatedClock for deterministic simulation time."""

import pytest
from datetime import datetime, timedelta, timezone

from sim.clock import SimulatedClock, JST


class TestSimulatedClock:
    def test_init_from_string(self):
        sc = SimulatedClock(start="2026-02-01T09:00:00+09:00")
        assert sc.now().hour == 9
        assert sc.now().tzinfo is not None

    def test_init_from_datetime(self):
        dt = datetime(2026, 2, 1, 9, 0, tzinfo=JST)
        sc = SimulatedClock(start=dt)
        assert sc.now() == dt

    def test_advance_minutes(self):
        sc = SimulatedClock(start="2026-02-01T09:00:00+09:00")
        sc.advance(minutes=5)
        assert sc.now().minute == 5

    def test_advance_seconds(self):
        sc = SimulatedClock(start="2026-02-01T09:00:00+09:00")
        sc.advance_seconds(90)
        assert sc.now().minute == 1
        assert sc.now().second == 30

    def test_now_utc(self):
        sc = SimulatedClock(start="2026-02-01T09:00:00+09:00")
        utc = sc.now_utc()
        assert utc.hour == 0  # 9AM JST = midnight UTC

    def test_elapsed_since(self):
        sc = SimulatedClock(start="2026-02-01T09:00:00+09:00")
        start = sc.now()
        sc.advance(minutes=30)
        elapsed = sc.elapsed_since(start)
        assert elapsed == timedelta(minutes=30)

    def test_total_elapsed(self):
        sc = SimulatedClock(start="2026-02-01T09:00:00+09:00")
        sc.advance(minutes=60)
        assert sc.total_elapsed() == timedelta(hours=1)

    def test_hour_property(self):
        sc = SimulatedClock(start="2026-02-01T14:30:00+09:00")
        assert sc.hour == 14

    def test_sleep_window(self):
        # 3AM JST — in sleep window
        sc = SimulatedClock(start="2026-02-01T03:00:00+09:00")
        assert sc.is_sleep_window is True

        # 6AM JST — out of sleep window
        sc = SimulatedClock(start="2026-02-01T06:00:00+09:00")
        assert sc.is_sleep_window is False

        # 9AM JST — out of sleep window
        sc = SimulatedClock(start="2026-02-01T09:00:00+09:00")
        assert sc.is_sleep_window is False

    def test_nap_window(self):
        sc = SimulatedClock(start="2026-02-01T14:30:00+09:00")
        assert sc.is_nap_window is True

        sc = SimulatedClock(start="2026-02-01T10:00:00+09:00")
        assert sc.is_nap_window is False

    def test_cycle_number(self):
        sc = SimulatedClock(start="2026-02-01T09:00:00+09:00")
        assert sc.cycle_number_since_start() == 0
        sc.advance(minutes=5)
        assert sc.cycle_number_since_start() == 1
        sc.advance(minutes=25)
        assert sc.cycle_number_since_start() == 6

    def test_simulated_day(self):
        sc = SimulatedClock(start="2026-02-01T09:00:00+09:00")
        assert sc.simulated_day() == 0
        sc.advance(minutes=24 * 60)
        assert sc.simulated_day() == 1
        sc.advance(minutes=24 * 60)
        assert sc.simulated_day() == 2

    def test_deterministic(self):
        """Two clocks with same start should produce identical results."""
        sc1 = SimulatedClock(start="2026-02-01T09:00:00+09:00")
        sc2 = SimulatedClock(start="2026-02-01T09:00:00+09:00")
        for _ in range(100):
            sc1.advance(minutes=5)
            sc2.advance(minutes=5)
        assert sc1.now() == sc2.now()

    def test_repr(self):
        sc = SimulatedClock(start="2026-02-01T09:00:00+09:00")
        assert "SimulatedClock" in repr(sc)
        assert "2026" in repr(sc)
