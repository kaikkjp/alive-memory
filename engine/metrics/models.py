"""Metric dataclasses for TASK-071 liveness metrics."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MetricResult:
    """Result of a single metric calculation."""
    name: str
    value: float
    details: dict = field(default_factory=dict)
    display: str = ''

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'value': self.value,
            'details': self.details,
            'display': self.display,
        }


@dataclass
class MetricSnapshot:
    """A point-in-time snapshot of all computed metrics."""
    timestamp: str
    period: str  # 'hourly' | 'daily' | 'lifetime'
    metrics: list[MetricResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp,
            'period': self.period,
            'metrics': [m.to_dict() for m in self.metrics],
        }
