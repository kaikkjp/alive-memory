"""Visitor Simulator — scripted visitor encounters for simulation mode.

Loads visitor scripts from a JSON file and converts them into a
chronological event queue. simulate.py polls get_due_events() each tick
to inject visitor events into the pipeline.

The pipeline doesn't know the difference between real and simulated
visitors — the engagement FSM, arbiter bypass, Cortex visitor handling
all run identically.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class VisitorEvent:
    """A single visitor event at an absolute simulation time."""
    time: datetime
    event_type: str          # 'visitor_connect' | 'visitor_speech' | 'visitor_disconnect'
    visitor_id: str
    display_name: str
    text: Optional[str] = None
    drop_url: Optional[str] = None


class VisitorSimulator:
    """Builds and serves a time-ordered queue of scripted visitor events.

    Usage:
        vs = VisitorSimulator('content/simulation-visitors.json', sim_start)
        while clock.now() < target:
            for event in vs.get_due_events(clock.now()):
                # inject event into pipeline
    """

    def __init__(self, script_path: str, sim_start: datetime):
        with open(script_path) as f:
            self._script = json.load(f)
        self._sim_start = sim_start
        self._pending: list[VisitorEvent] = self._build_event_queue()

    def _build_event_queue(self) -> list[VisitorEvent]:
        """Flatten visitor scripts into chronological event queue."""
        events = []
        for visitor in self._script:
            # Arrival = midnight of sim start + (arrive_day - 1) days + arrive_hour
            day_start = self._sim_start.replace(
                hour=0, minute=0, second=0, microsecond=0,
            ) + timedelta(days=visitor['arrive_day'] - 1)
            base_time = day_start + timedelta(hours=visitor['arrive_hour'])

            # Connect event
            events.append(VisitorEvent(
                time=base_time,
                event_type='visitor_connect',
                visitor_id=visitor['visitor_id'],
                display_name=visitor['display_name'],
            ))

            # Speech events
            for msg in visitor['messages']:
                msg_time = base_time + timedelta(minutes=msg['delay_min'])
                events.append(VisitorEvent(
                    time=msg_time,
                    event_type='visitor_speech',
                    visitor_id=visitor['visitor_id'],
                    display_name=visitor['display_name'],
                    text=msg['text'],
                    drop_url=msg.get('drop_url'),
                ))

            # Disconnect: 5 min after the latest message (max, not last-written)
            max_delay = max((msg['delay_min'] for msg in visitor['messages']), default=0)
            events.append(VisitorEvent(
                time=base_time + timedelta(minutes=max_delay + 5),
                event_type='visitor_disconnect',
                visitor_id=visitor['visitor_id'],
                display_name=visitor['display_name'],
            ))

        events.sort(key=lambda e: e.time)
        return events

    def get_due_events(self, current_time: datetime) -> list[VisitorEvent]:
        """Return and consume all events at or before current_time."""
        due = []
        while self._pending and self._pending[0].time <= current_time:
            due.append(self._pending.pop(0))
        return due

    def has_remaining(self) -> bool:
        return len(self._pending) > 0

    def next_event_time(self) -> Optional[datetime]:
        return self._pending[0].time if self._pending else None

    @property
    def encounter_count(self) -> int:
        """Number of visitor encounters in the script."""
        return len(self._script)
