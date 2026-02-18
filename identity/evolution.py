"""
Identity Evolution — STUB MODULE

THIS IS A STUB. All methods raise NotImplementedError.
Implementation is gated on resolving the philosophical question:
who decides what "genuine growth" vs "unwanted drift" looks like?

The philosophical problem:
- If she always accepts drift → identity dissolves
- If she always corrects → she's frozen, can't grow
- If we hardcode the criteria → we decide her identity for her
- If she decides → the decision is influenced by current drift (circular)

Guard rails (non-negotiable regardless of future implementation):
1. Core safety traits cannot be evolved away
2. Evolution rate capped — max one trait update per sleep cycle
3. All evolution decisions logged with full context
4. Operator override via dashboard

See: tasks/TASK-063-identity-evolution.md
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data models (stubs for TASK-062 drift reports)
# ---------------------------------------------------------------------------

class EvolutionAction(Enum):
    """Possible responses to detected drift."""
    ACCEPT = "accept"    # Incorporate drift as new baseline
    CORRECT = "correct"  # Steer back toward previous baseline
    DEFER = "defer"      # Take no action, continue observing


@dataclass
class DriftReport:
    """Minimal stub for drift detection output (TASK-062).

    Real implementation will come from TASK-062's drift detection module.
    This exists only so the interface is importable and testable.
    """
    trait_name: str
    baseline_value: float
    current_value: float
    drift_magnitude: float
    sustained_cycles: int = 0
    context: str = ""


@dataclass
class EvolutionDecision:
    """Result of evaluating a drift report."""
    action: EvolutionAction
    trait_name: str
    reason: str
    confidence: float = 0.0


@dataclass
class GuardRailConfig:
    """Loaded from identity/evolution_config.json."""
    protected_traits: list[str] = field(default_factory=list)
    max_updates_per_sleep: int = 1
    min_sustained_cycles: int = 3
    operator_override_enabled: bool = True

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "GuardRailConfig":
        """Load guard rail configuration from JSON file.

        Falls back to defaults if the file is missing or unreadable,
        since the evolution feature is disabled behind a philosophical gate.
        """
        if path is None:
            path = Path(__file__).parent / "evolution_config.json"
        if not path.exists():
            print(f"[IdentityEvolution] Config not found: {path} — using defaults")
            return cls()
        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[IdentityEvolution] Failed to read config: {exc} — using defaults")
            return cls()
        return cls(
            protected_traits=data.get("protected_traits", []),
            max_updates_per_sleep=data.get("max_updates_per_sleep", 1),
            min_sustained_cycles=data.get("min_sustained_cycles", 3),
            operator_override_enabled=data.get("operator_override_enabled", True),
        )


# ---------------------------------------------------------------------------
# Stub interface
# ---------------------------------------------------------------------------

_GATE_MSG = (
    "Identity evolution is disabled — pending philosophical review. "
    "See TASK-063 spec for details."
)


class IdentityEvolution:
    """Stub interface for identity evolution.

    All methods raise NotImplementedError until the philosophical gate
    is resolved. This class exists to:
    1. Define the contract future implementation must fulfill
    2. Allow tests to verify the interface exists
    3. Allow dashboard to report disabled status
    """

    def __init__(self) -> None:
        self._config = GuardRailConfig.load()

    @property
    def config(self) -> GuardRailConfig:
        return self._config

    @property
    def enabled(self) -> bool:
        """Always False for the stub."""
        return False

    @property
    def status_message(self) -> str:
        """Human-readable status for dashboard display."""
        return "disabled — pending review"

    def evaluate_drift(self, drift_report: DriftReport) -> EvolutionDecision:
        """Given a drift report, decide: accept, correct, or defer."""
        raise NotImplementedError(_GATE_MSG)

    def accept_drift(self, drift_report: DriftReport) -> None:
        """Update self-model baseline to incorporate the drift as new normal."""
        raise NotImplementedError(_GATE_MSG)

    def correct_drift(self, drift_report: DriftReport) -> None:
        """Inject corrective guidance into next N cycles to steer back toward baseline."""
        raise NotImplementedError(_GATE_MSG)

    def defer(self, drift_report: DriftReport) -> None:
        """Take no action. Continue observing."""
        raise NotImplementedError(_GATE_MSG)
