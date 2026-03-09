"""Load scenarios from builtin directory or custom path."""

from __future__ import annotations

import pathlib

from alive_memory.autotune.scenarios.schema import parse_scenario_yaml
from alive_memory.autotune.types import Scenario

_BUILTIN_DIR = pathlib.Path(__file__).parent / "builtin"


def load_scenarios(source: str = "builtin") -> list[Scenario]:
    """Load scenarios from a source.

    Args:
        source: "builtin" for built-in scenarios, or a directory path.

    Returns:
        List of parsed Scenario objects.
    """
    scenario_dir = _BUILTIN_DIR if source == "builtin" else pathlib.Path(source)

    if not scenario_dir.is_dir():
        raise FileNotFoundError(f"Scenario directory not found: {scenario_dir}")

    scenarios = []
    for path in sorted(scenario_dir.glob("*.yaml")):
        scenarios.append(parse_scenario_yaml(path))

    if not scenarios:
        raise ValueError(f"No .yaml scenario files found in {scenario_dir}")

    return scenarios
