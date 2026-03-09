"""Clock abstraction for alive-memory.

Provides a Clock protocol with SystemClock (real time) and SimulatedClock
(manually controllable time for testing and autotune).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Protocol for time sources."""

    def now(self) -> datetime: ...


class SystemClock:
    """Default clock — returns real wall time."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class SimulatedClock:
    """Clock with manually controllable time for testing and autotune."""

    def __init__(self, start: datetime | None = None):
        self._time = start or datetime.now(UTC)

    def now(self) -> datetime:
        return self._time

    def advance(self, seconds: float) -> None:
        self._time += timedelta(seconds=seconds)

    def set(self, dt: datetime) -> None:
        self._time = dt
