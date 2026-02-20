"""sim.baselines.stateless — Baseline A: Stateless chatbot.

No memory, no drives, no sleep. Just prompt + respond.
This is "ChatGPT with a character card" — the simplest possible
comparison system.

Only responds when a visitor message is present.
Otherwise returns idle.
"""

from __future__ import annotations


class StatelessBaseline:
    """Stateless chatbot baseline. No memory, no drives, no sleep."""

    def should_sleep(self, clock) -> bool:
        """Stateless baseline never sleeps."""
        return False

    def pre_cycle(self, drives: dict, engagement: dict, events: list):
        """Override drives to be flat — stateless has no internal state."""
        drives["social_hunger"] = 0.5
        drives["curiosity"] = 0.5
        drives["expression_need"] = 0.3
        drives["rest_need"] = 0.2
        drives["energy"] = 0.8
        drives["mood_valence"] = 0.0
        drives["mood_arousal"] = 0.3
