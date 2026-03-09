"""Scenario YAML parser."""

from __future__ import annotations

import pathlib
from typing import Any

from alive_memory.autotune.types import ExpectedRecall, Scenario, ScenarioTurn


def parse_scenario_yaml(path: pathlib.Path) -> Scenario:
    """Parse a scenario YAML file into a Scenario dataclass."""
    import yaml

    with open(path) as f:
        data = yaml.safe_load(f)

    return _parse_scenario_dict(data)


def _parse_scenario_dict(data: dict[str, Any]) -> Scenario:
    """Parse a scenario from a dict."""
    turns = []
    for t in data.get("turns", []):
        expected = None
        if "expected_recall" in t:
            er = t["expected_recall"]
            expected = ExpectedRecall(
                must_contain=er.get("must_contain", []),
                must_not_contain=er.get("must_not_contain", []),
                min_results=er.get("min_results", 1),
            )
        turns.append(
            ScenarioTurn(
                role=t.get("role", "user"),
                action=t.get("action", "intake"),
                content=t.get("content", ""),
                simulated_time=t.get("simulated_time"),
                advance_seconds=t.get("advance_seconds", 0),
                metadata=t.get("metadata", {}),
                expected_recall=expected,
            )
        )

    return Scenario(
        name=data["name"],
        description=data.get("description", ""),
        category=data.get("category", ""),
        turns=turns,
        setup_config=data.get("setup_config"),
    )
