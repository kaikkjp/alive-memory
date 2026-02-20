"""sim.scenario — ScenarioManager for timed event injection.

Defines ScenarioEvent and ScenarioManager for injecting events at
specific cycle numbers during simulation. Events include visitor
arrivals, messages, departures, X mentions, and drive overrides.

Usage:
    from sim.scenario import ScenarioManager
    sm = ScenarioManager.load("standard")
    events = sm.get_events(100)  # events for cycle 100
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ScenarioEvent:
    """A single scheduled event in a simulation scenario."""
    cycle: int                    # which cycle to inject
    event_type: str               # visitor_arrive, visitor_message, visitor_leave,
                                  # x_mention, set_drives, inject_thread
    payload: dict = field(default_factory=dict)

    def to_pipeline_event(self, timestamp: datetime) -> dict:
        """Convert to a dict suitable for injection into the sim DB."""
        event_id = str(uuid.uuid4())[:12]

        if self.event_type == "visitor_arrive":
            return {
                "id": event_id,
                "event_type": "visitor_connect",
                "source": self.payload.get("source", "sim:unknown"),
                "content": self.payload.get("name", "Visitor"),
                "metadata": f'{{"channel": "{self.payload.get("channel", "telegram")}"}}',
                "salience": 0.8,
                "created_at": timestamp.isoformat(),
            }
        elif self.event_type == "visitor_message":
            return {
                "id": event_id,
                "event_type": "visitor_speech",
                "source": self.payload.get("source", "sim:unknown"),
                "content": self.payload.get("content", ""),
                "metadata": "{}",
                "salience": 0.9,
                "created_at": timestamp.isoformat(),
            }
        elif self.event_type == "visitor_leave":
            return {
                "id": event_id,
                "event_type": "visitor_disconnect",
                "source": self.payload.get("source", "sim:unknown"),
                "content": "",
                "metadata": "{}",
                "salience": 0.6,
                "created_at": timestamp.isoformat(),
            }
        elif self.event_type == "x_mention":
            return {
                "id": event_id,
                "event_type": "x_mention",
                "source": self.payload.get("source", "x:unknown"),
                "content": self.payload.get("content", ""),
                "metadata": "{}",
                "salience": 0.5,
                "created_at": timestamp.isoformat(),
            }
        elif self.event_type in ("set_drives", "inject_thread"):
            # These are meta-events handled by the runner, not injected as DB events
            return {
                "id": event_id,
                "event_type": self.event_type,
                "source": "sim:scenario",
                "content": "",
                "metadata": "{}",
                "salience": 0.0,
                "created_at": timestamp.isoformat(),
                "_payload": self.payload,
            }
        else:
            return {
                "id": event_id,
                "event_type": self.event_type,
                "source": self.payload.get("source", "sim:scenario"),
                "content": self.payload.get("content", ""),
                "metadata": "{}",
                "salience": 0.5,
                "created_at": timestamp.isoformat(),
            }


class ScenarioManager:
    """Manages timed event injection into simulation."""

    def __init__(self, events: list[ScenarioEvent], name: str = "custom"):
        self.events = sorted(events, key=lambda e: e.cycle)
        self.name = name
        self._index = 0

    def get_events(self, cycle: int) -> list[ScenarioEvent]:
        """Return all events scheduled for this cycle."""
        result = []
        while self._index < len(self.events) and self.events[self._index].cycle <= cycle:
            if self.events[self._index].cycle == cycle:
                result.append(self.events[self._index])
            self._index += 1
        return result

    def reset(self):
        """Reset index for re-running the scenario."""
        self._index = 0

    @property
    def total_events(self) -> int:
        return len(self.events)

    @staticmethod
    def load(name: str) -> ScenarioManager:
        """Load a named scenario."""
        from sim.scenarios.standard import build_standard_scenario
        from sim.scenarios.stress import (
            build_death_spiral_scenario,
            build_visitor_flood_scenario,
            build_isolation_scenario,
            build_spam_attack_scenario,
            build_sleep_deprivation_scenario,
        )
        from sim.scenarios.longitudinal import build_longitudinal_scenario

        scenarios = {
            "standard": build_standard_scenario,
            "longitudinal": build_longitudinal_scenario,
            "death_spiral": build_death_spiral_scenario,
            "visitor_flood": build_visitor_flood_scenario,
            "isolation": build_isolation_scenario,
            "spam_attack": build_spam_attack_scenario,
            "sleep_deprivation": build_sleep_deprivation_scenario,
        }
        if name not in scenarios:
            raise ValueError(f"Unknown scenario: {name}. Available: {list(scenarios.keys())}")
        return scenarios[name]()

    def __repr__(self) -> str:
        return f"ScenarioManager(name={self.name!r}, events={len(self.events)})"
