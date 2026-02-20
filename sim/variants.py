"""sim.variants — Ablated pipeline variants for ablation study.

Each variant removes one component from the full ALIVE pipeline:
- no_drives: flat drives, no hypothalamus
- no_sleep: never sleeps, no consolidation
- no_affect: locked valence=0.0, arousal=0.3
- no_basal_ganglia: every intention executes (no gating)
- no_memory: no memory recall or updates
"""

from __future__ import annotations

from sim.clock import SimulatedClock


# Constants for ablation overrides
FLAT_DRIVES = {
    "social_hunger": 0.5,
    "curiosity": 0.5,
    "expression_need": 0.3,
    "rest_need": 0.2,
    "energy": 0.8,
    "mood_valence": 0.0,
    "mood_arousal": 0.3,
}

NEUTRAL_AFFECT = {
    "mood_valence": 0.0,
    "mood_arousal": 0.3,
}


class AblatedPipeline:
    """Full ALIVE pipeline with one component surgically removed."""

    def __init__(self, remove: str):
        """
        Args:
            remove: Component to ablate. One of:
                    drives, sleep, affect, basal_ganglia, memory
        """
        valid = {"drives", "sleep", "affect", "basal_ganglia", "memory"}
        if remove not in valid:
            raise ValueError(
                f"Unknown ablation target: {remove}. Valid: {valid}"
            )
        self.remove = remove

    def should_sleep(self, clock: SimulatedClock) -> bool:
        """Ablation: no_sleep variant never sleeps."""
        if self.remove == "sleep":
            return False
        return clock.is_sleep_window

    def pre_cycle(self, drives: dict, engagement: dict, events: list):
        """Apply ablation overrides before each cycle."""
        if self.remove == "drives":
            # Flat drives — no internal state changes
            for key, value in FLAT_DRIVES.items():
                drives[key] = value

        elif self.remove == "affect":
            # Lock mood to neutral
            for key, value in NEUTRAL_AFFECT.items():
                drives[key] = value

        elif self.remove == "memory":
            # Memory ablation happens at the runner level
            # (skip memory_updates in cycle result)
            pass

        elif self.remove == "basal_ganglia":
            # No gating — all intentions pass through
            # This is handled in the runner when processing intentions
            pass

        # sleep and memory ablation don't need pre_cycle overrides

    @property
    def label(self) -> str:
        """Human-readable label for this ablation."""
        labels = {
            "drives": "No Drives (flat hypothalamus)",
            "sleep": "No Sleep (no consolidation)",
            "affect": "No Affect (neutral mood locked)",
            "basal_ganglia": "No Basal Ganglia (no action gating)",
            "memory": "No Memory (no recall/updates)",
        }
        return labels.get(self.remove, f"no_{self.remove}")
