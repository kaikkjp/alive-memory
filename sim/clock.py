"""sim.clock — SimulatedClock for deterministic, accelerated simulation time.

Wraps the existing clock.py module to provide a simulation-friendly
interface with advance-by-minutes, sleep window detection, and
deterministic time progression.

Usage:
    from sim.clock import SimulatedClock
    sc = SimulatedClock(start="2026-02-01T09:00:00+09:00")
    sc.advance(minutes=5)
    print(sc.now())          # 2026-02-01 09:05:00+09:00
    print(sc.is_sleep_window) # False
"""

from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


class SimulatedClock:
    """Deterministic clock for reproducible simulations.

    Unlike the global clock.py module, SimulatedClock is an instance
    that doesn't affect the module-level singleton. Multiple simulations
    can run with independent clocks.
    """

    def __init__(self, start: str = "2026-02-01T09:00:00+09:00"):
        if isinstance(start, str):
            self.current = datetime.fromisoformat(start)
        else:
            self.current = start
        # Ensure timezone-aware
        if self.current.tzinfo is None:
            self.current = self.current.replace(tzinfo=JST)
        self.cycle_duration = timedelta(minutes=5)
        self._start = self.current

    def now(self) -> datetime:
        """Current simulated time (JST)."""
        return self.current.astimezone(JST)

    def now_utc(self) -> datetime:
        """Current simulated time (UTC)."""
        return self.current.astimezone(timezone.utc)

    def advance(self, minutes: int = 5):
        """Advance simulated time by the given number of minutes."""
        self.current += timedelta(minutes=minutes)

    def advance_seconds(self, seconds: float):
        """Advance simulated time by the given number of seconds."""
        self.current += timedelta(seconds=seconds)

    def elapsed_since(self, timestamp: datetime) -> timedelta:
        """Time elapsed since a given timestamp."""
        return self.current - timestamp

    def total_elapsed(self) -> timedelta:
        """Total time elapsed since simulation start."""
        return self.current - self._start

    @property
    def hour(self) -> int:
        """Current hour in JST."""
        return self.now().hour

    @property
    def is_sleep_window(self) -> bool:
        """True if current time is in the sleep window (3AM-6AM JST)."""
        h = self.hour
        return 3 <= h < 6

    @property
    def is_nap_window(self) -> bool:
        """True if current time is in a typical nap window (2PM-4PM JST)."""
        h = self.hour
        return 14 <= h < 16

    def cycle_number_since_start(self) -> int:
        """How many 5-minute cycles have elapsed since start."""
        elapsed = self.total_elapsed()
        return int(elapsed.total_seconds() / self.cycle_duration.total_seconds())

    def simulated_day(self) -> int:
        """Day number (0-indexed) since simulation start."""
        return self.total_elapsed().days

    def __repr__(self) -> str:
        return f"SimulatedClock({self.now().isoformat()})"
