"""Autotune scenario loading."""

from __future__ import annotations

from alive_memory.autotune.scenarios.loader import load_scenarios
from alive_memory.autotune.scenarios.schema import parse_scenario_yaml

__all__ = ["load_scenarios", "parse_scenario_yaml"]
