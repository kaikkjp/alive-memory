"""Virtual clock — drop-in time source for the shopkeeper.

Real time in production, virtual (instant-advance) in simulation.
All files that need timestamps import this module instead of calling
datetime.now() directly.

Production is unaffected: the default module-level singleton is a
real-time clock. Only simulate.py calls init_clock(simulate=True).
"""

from datetime import datetime, timedelta, timezone

# JST constant — canonical timezone for the shopkeeper
JST = timezone(timedelta(hours=9))


class Clock:
    """Drop-in time source. Real time in production, virtual in simulation."""

    def __init__(self, simulate: bool = False,
                 start: datetime = None,
                 speed: float = 1.0):
        self._simulate = simulate
        self._speed = speed
        # Default start: 7:00 AM JST today (she wakes up)
        self._virtual_now = start or datetime.now(JST).replace(
            hour=7, minute=0, second=0, microsecond=0
        )

    def now(self) -> datetime:
        """Current time in JST."""
        if self._simulate:
            return self._virtual_now
        return datetime.now(JST)

    def now_utc(self) -> datetime:
        """Current time in UTC."""
        if self._simulate:
            return self._virtual_now.astimezone(timezone.utc)
        return datetime.now(timezone.utc)

    def advance(self, seconds: float):
        """In simulate mode, jump forward. In production, no-op."""
        if self._simulate:
            self._virtual_now += timedelta(seconds=seconds)

    @property
    def is_simulating(self) -> bool:
        return self._simulate


# Module-level singleton, set once at startup
_clock = Clock()


def init_clock(simulate=False, start=None, speed=1.0):
    """Replace the module-level clock. Call once at startup."""
    global _clock
    _clock = Clock(simulate=simulate, start=start, speed=speed)


def now() -> datetime:
    """Current time in JST."""
    return _clock.now()


def now_utc() -> datetime:
    """Current time in UTC."""
    return _clock.now_utc()


def advance(seconds: float):
    """Advance virtual clock (no-op in production)."""
    _clock.advance(seconds)


def is_simulating() -> bool:
    return _clock.is_simulating
