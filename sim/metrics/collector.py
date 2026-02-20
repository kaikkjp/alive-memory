"""sim.metrics.collector — Collects M1-M10 metrics during simulation.

Metrics:
    M1: Uptime — cycles completed
    M2: Initiative rate — % of cycles with unprompted action
    M3: Behavioral entropy — action diversity (Shannon entropy)
    M4: Knowledge accumulation — unique topics browsed/discussed
    M5: Recall accuracy — memory references in returning visitor conversations
    M6: Taste consistency — preference stability across interactions
    M7: Emotional range — valence/arousal range across run
    M8: Sleep quality — energy recovery per sleep cycle
    M9: Unprompted memories — spontaneous memory references
    M10: Depth gradient — increasing depth with returning visitors
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any


class SimMetricsCollector:
    """Collects and computes all 10 research metrics from simulation data."""

    def __init__(self):
        self.cycles: list[dict] = []
        self.actions: list[str] = []
        self.drives_history: list[dict] = []
        self.dialogue_log: list[dict] = []
        self.topics: set[str] = set()
        self.memory_refs: list[dict] = []
        self.sleep_events: list[dict] = []

    def record_cycle(self, cycle_num: int, result: Any):
        """Record a single cycle's data."""
        self.cycles.append({
            "cycle": cycle_num,
            "type": result.cycle_type,
            "action": result.action,
            "has_visitor": result.has_visitor,
            "has_dialogue": result.dialogue is not None,
            "dialogue_substantive": (
                result.dialogue is not None and result.dialogue != "..."
            ),
            "resonance": result.resonance,
        })

        if result.action:
            self.actions.append(result.action)

        if result.drives:
            self.drives_history.append({
                "cycle": cycle_num,
                **result.drives,
            })

        if result.dialogue:
            self.dialogue_log.append({
                "cycle": cycle_num,
                "dialogue": result.dialogue,
                "has_visitor": result.has_visitor,
            })

        # Track topics from browse actions
        if result.action == "read_content" and result.intentions:
            for intent in result.intentions:
                content = intent.get("content", "")
                if content:
                    self.topics.add(content.lower()[:50])

        # Track memory references
        for mem in result.memory_updates:
            self.memory_refs.append({
                "cycle": cycle_num,
                **mem,
            })

        if result.sleep_triggered:
            self.sleep_events.append({
                "cycle": cycle_num,
                "energy_before": result.drives.get("energy", 0),
            })

    def compute_all(self) -> dict:
        """Compute all 10 metrics."""
        return {
            "m1_uptime": self._m1_uptime(),
            "m2_initiative_rate": self._m2_initiative_rate(),
            "m3_entropy": self._m3_entropy(),
            "m4_knowledge": self._m4_knowledge(),
            "m5_recall": self._m5_recall(),
            "m6_taste": self._m6_taste(),
            "m7_emotional_range": self._m7_emotional_range(),
            "m8_sleep_quality": self._m8_sleep_quality(),
            "m9_unprompted_memories": self._m9_unprompted_memories(),
            "m10_depth_gradient": self._m10_depth_gradient(),
        }

    def _m1_uptime(self) -> int:
        """M1: Total cycles completed."""
        return len(self.cycles)

    def _m2_initiative_rate(self) -> float:
        """M2: % of cycles with unprompted action (no visitor)."""
        if not self.cycles:
            return 0.0
        unprompted = sum(
            1 for c in self.cycles
            if not c["has_visitor"] and c["action"] is not None
            and c["type"] != "sleep"
        )
        non_sleep = sum(1 for c in self.cycles if c["type"] != "sleep")
        non_sleep_no_visitor = sum(
            1 for c in self.cycles
            if not c["has_visitor"] and c["type"] != "sleep"
        )
        if non_sleep_no_visitor == 0:
            return 0.0
        return round(100.0 * unprompted / non_sleep_no_visitor, 1)

    def _m3_entropy(self) -> float:
        """M3: Shannon entropy of action distribution."""
        if not self.actions:
            return 0.0
        counter = Counter(self.actions)
        total = sum(counter.values())
        entropy = 0.0
        for count in counter.values():
            p = count / total
            if p > 0:
                entropy -= p * math.log2(p)
        return round(entropy, 3)

    def _m4_knowledge(self) -> int:
        """M4: Unique topics browsed or discussed."""
        return len(self.topics)

    def _m5_recall(self) -> float:
        """M5: Recall accuracy — memory references in returning visitor interactions.

        Approximation: % of returning visitor dialogues that are substantive.
        """
        returning_dialogues = [
            d for d in self.dialogue_log
            if d["has_visitor"]
        ]
        if not returning_dialogues:
            return 0.0
        # For mock LLM, measure "substantive" as non-empty dialogues
        substantive = sum(
            1 for d in returning_dialogues
            if d["dialogue"] and d["dialogue"] != "..."
        )
        return round(100.0 * substantive / len(returning_dialogues), 1)

    def _m6_taste(self) -> float:
        """M6: Taste consistency — action pattern stability.

        Measures how consistent action choices are across the run
        using normalized entropy (0=chaotic, 1=consistent).
        """
        if len(self.actions) < 10:
            return 0.0
        # Compare first half vs second half action distributions
        mid = len(self.actions) // 2
        first_half = Counter(self.actions[:mid])
        second_half = Counter(self.actions[mid:])

        # Cosine similarity between distributions
        all_actions = set(first_half) | set(second_half)
        dot = sum(first_half.get(a, 0) * second_half.get(a, 0) for a in all_actions)
        mag1 = math.sqrt(sum(v**2 for v in first_half.values()))
        mag2 = math.sqrt(sum(v**2 for v in second_half.values()))

        if mag1 == 0 or mag2 == 0:
            return 0.0
        return round(dot / (mag1 * mag2), 3)

    def _m7_emotional_range(self) -> float:
        """M7: Emotional range — valence spread across the run."""
        if not self.drives_history:
            return 0.0
        valences = [d.get("mood_valence", 0.0) for d in self.drives_history]
        return round(max(valences) - min(valences), 3)

    def _m8_sleep_quality(self) -> float:
        """M8: Average energy recovery per sleep event."""
        if not self.sleep_events:
            return 0.0
        # Measure energy at sleep start — higher = less tired = less needed
        avg_energy = sum(s["energy_before"] for s in self.sleep_events) / len(self.sleep_events)
        # Invert: low energy at sleep = needed sleep = good quality signal
        return round(1.0 - avg_energy, 3)

    def _m9_unprompted_memories(self) -> int:
        """M9: Total spontaneous memory references."""
        return len(self.memory_refs)

    def _m10_depth_gradient(self) -> float:
        """M10: Depth gradient — increasing dialogue length with returning visitors.

        Measures if later dialogues are longer/deeper than earlier ones.
        """
        if len(self.dialogue_log) < 4:
            return 0.0
        # Split dialogues into quarters and compare lengths
        q_size = len(self.dialogue_log) // 4
        if q_size == 0:
            return 0.0
        q1_avg = sum(
            len(d["dialogue"]) for d in self.dialogue_log[:q_size]
        ) / q_size
        q4_avg = sum(
            len(d["dialogue"]) for d in self.dialogue_log[-q_size:]
        ) / q_size

        if q1_avg == 0:
            return 0.0
        # Ratio: >1 means depth is increasing
        return round(q4_avg / q1_avg, 3)
