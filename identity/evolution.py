"""Identity Evolution — Three-Tier Drift Resolution (TASK-092).

Replaces the philosophical gate stubs from TASK-063 with working logic.

The question "who decides what 'genuine growth' vs 'unwanted drift' looks like?"
is resolved by three tiers operating simultaneously:

    Tier 1 — Operator: Hard floor bounds + protected traits (alive_config.yaml)
    Tier 2 — Homeostasis: Meta-controller automatic corrections (TASK-090)
    Tier 3 — Conscious: Her deliberate modify_self choices, protected for N cycles

Decision sequence for each drifted parameter:
    1. Guard rail check — protected traits cannot evolve
    2. Conscious protection — recent modify_self? Defer to her choice
    3. Meta-controller pending — already being handled? Defer
    4. Organic vs sudden — baseline shifted gradually? Accept. Otherwise correct.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import db
from alive_config import cfg_section
from models.event import Event


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class EvolutionAction(Enum):
    """Possible responses to detected drift."""
    ACCEPT = "accept"    # Incorporate drift as new baseline
    CORRECT = "correct"  # Steer back toward previous baseline
    DEFER = "defer"      # Take no action, continue observing


@dataclass
class DriftReport:
    """Per-parameter drift report for evolution evaluation."""
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
    """Loaded from identity/evolution_config.json (backward compat)."""
    protected_traits: list[str] = field(default_factory=list)
    max_updates_per_sleep: int = 1
    min_sustained_cycles: int = 3
    operator_override_enabled: bool = True

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "GuardRailConfig":
        """Load guard rail configuration from JSON file.

        Falls back to defaults if the file is missing or unreadable.
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
# Core implementation
# ---------------------------------------------------------------------------

class IdentityEvolution:
    """Three-tier identity evolution engine.

    Evaluates parameter drift and decides: accept (organic growth),
    correct (sudden drift), or defer (conscious choice / already handled).
    """

    def __init__(self) -> None:
        self._yaml_config = cfg_section('identity_evolution') or {}
        self._guard_rails = GuardRailConfig.load()
        self._updates_this_sleep = 0

    @property
    def config(self) -> GuardRailConfig:
        return self._guard_rails

    @property
    def enabled(self) -> bool:
        return self._yaml_config.get('enabled', False)

    @property
    def status_message(self) -> str:
        if not self.enabled:
            return "disabled"
        return "active"

    @property
    def protected_traits(self) -> list[str]:
        """Merge protected traits from YAML config and JSON guard rails."""
        yaml_traits = self._yaml_config.get('protected_traits', [])
        json_traits = self._guard_rails.protected_traits
        return list(set(yaml_traits + json_traits))

    @property
    def max_updates_per_sleep(self) -> int:
        return self._yaml_config.get(
            'max_updates_per_sleep',
            self._guard_rails.max_updates_per_sleep,
        )

    @property
    def conscious_protection_cycles(self) -> int:
        return self._yaml_config.get('conscious_protection_cycles', 500)

    @property
    def baseline_shift_window(self) -> int:
        return self._yaml_config.get('baseline_shift_window', 1000)

    @property
    def organic_growth_threshold(self) -> float:
        return self._yaml_config.get('organic_growth_threshold', 0.15)

    def can_update(self) -> bool:
        """Check if we haven't exceeded the per-sleep rate limit."""
        return self._updates_this_sleep < self.max_updates_per_sleep

    async def evaluate_drift(
        self, drift_report: DriftReport, cycle_count: int,
    ) -> EvolutionDecision:
        """Core decision logic. Evaluates a single drifted parameter.

        Decision sequence:
        1. Guard rails — protected traits always defer
        2. Conscious protection — recent modify_self defers
        3. Meta-controller pending — already being handled defers
        4. Organic growth vs sudden drift — baseline shift decides
        """
        param = drift_report.trait_name

        # 1. Guard rail check — protected traits cannot evolve
        if self._is_protected(param):
            return EvolutionDecision(
                action=EvolutionAction.DEFER,
                trait_name=param,
                reason=f"protected trait — cannot evolve '{param}'",
            )

        # 2. Conscious protection — was this param recently set by modify_self?
        conscious_mods = await db.get_conscious_modifications(
            window_cycles=self.conscious_protection_cycles,
            cycle_count=cycle_count,
            param_names=[param],
        )
        if conscious_mods:
            return EvolutionDecision(
                action=EvolutionAction.DEFER,
                trait_name=param,
                reason=f"conscious override active for '{param}' — respecting her choice",
            )

        # 3. Meta-controller pending — is the meta-controller already handling this?
        pending = await db.get_pending_experiments()
        for exp in pending:
            if exp.get('param_name') == param:
                return EvolutionDecision(
                    action=EvolutionAction.DEFER,
                    trait_name=param,
                    reason=f"meta-controller adjustment pending for '{param}'",
                )

        # 4. Organic growth vs sudden drift
        drift_info = await db.get_param_drift(
            param_name=param,
            window_cycles=self.baseline_shift_window,
            cycle_count=cycle_count,
        )

        min_steps = self._guard_rails.min_sustained_cycles
        mod_count = drift_info.get('modification_count', 1) if drift_info else 0

        if (drift_info
                and drift_info['shift'] >= self.organic_growth_threshold
                and mod_count >= min_steps):
            # Baseline shifted gradually over multiple steps — organic growth
            return EvolutionDecision(
                action=EvolutionAction.ACCEPT,
                trait_name=param,
                reason="baseline shifted gradually — organic growth",
                confidence=min(drift_info['shift'] / 0.3, 1.0),
            )
        else:
            # Either small shift, or large shift in too few steps — sudden drift
            return EvolutionDecision(
                action=EvolutionAction.CORRECT,
                trait_name=param,
                reason="sudden drift without baseline shift",
                confidence=0.7,
            )

    async def accept_drift(self, drift_report: DriftReport) -> None:
        """Accept drift as genuine growth. Emit event for awareness."""
        self._updates_this_sleep += 1

        event = Event(
            event_type='identity_evolution',
            source='self',
            payload={
                'type': 'accepted',
                'param': drift_report.trait_name,
                'baseline_value': drift_report.baseline_value,
                'current_value': drift_report.current_value,
                'drift_magnitude': drift_report.drift_magnitude,
                'reason': 'organic growth',
            },
            channel='system',
            salience_base=0.5,
        )
        await db.append_event(event)
        try:
            await db.inbox_add(event.id, priority=0.5)
        except Exception:
            pass
        print(f"  [IdentityEvolution] Accepted drift for {drift_report.trait_name}: "
              f"organic growth ({drift_report.drift_magnitude:.3f})")

    async def correct_drift(self, drift_report: DriftReport) -> None:
        """Correct sudden drift via meta-controller. Emit event."""
        from sleep.meta_controller import request_correction

        self._updates_this_sleep += 1

        result = await request_correction(
            param_name=drift_report.trait_name,
            target_value=drift_report.baseline_value,
        )

        event = Event(
            event_type='identity_evolution',
            source='self',
            payload={
                'type': 'corrected',
                'param': drift_report.trait_name,
                'baseline_value': drift_report.baseline_value,
                'current_value': drift_report.current_value,
                'drift_magnitude': drift_report.drift_magnitude,
                'reason': 'sudden drift',
                'correction_applied': result is not None,
            },
            channel='system',
            salience_base=0.5,
        )
        await db.append_event(event)
        try:
            await db.inbox_add(event.id, priority=0.5)
        except Exception:
            pass
        print(f"  [IdentityEvolution] Corrected drift for {drift_report.trait_name}: "
              f"sudden drift ({drift_report.drift_magnitude:.3f})")

    async def defer(self, drift_report: DriftReport, reason: str) -> None:
        """No action — but persist for dashboard visibility."""
        event = Event(
            event_type='identity_evolution',
            source='self',
            payload={
                'type': 'deferred',
                'param': drift_report.trait_name,
                'baseline_value': drift_report.baseline_value,
                'current_value': drift_report.current_value,
                'drift_magnitude': drift_report.drift_magnitude,
                'reason': reason,
            },
            channel='system',
            salience_base=0.1,
        )
        await db.append_event(event)
        print(f"  [IdentityEvolution] Deferred {drift_report.trait_name}: {reason}")

    # ── Internal helpers ──

    def _is_protected(self, param_name: str) -> bool:
        """Check if a parameter maps to a protected trait.

        Protected traits are specified as short names (e.g. 'curiosity').
        Parameters use dotted paths (e.g. 'hypothalamus.equilibria.diversive_curiosity').
        Match if any protected trait appears as a substring of the param name.
        """
        for trait in self.protected_traits:
            if trait in param_name:
                return True
        return False
