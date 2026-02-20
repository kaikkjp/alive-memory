"""sim.baselines.react_agent — Baseline B: ReAct agent.

Memory (conversation history) + tools, but no drives, no sleep,
no affect. Standard agent pattern — LangChain/AutoGPT-style.

Maintains a rolling conversation history window.
Can use tools (browse, post, journal) but has no internal motivation.
"""

from __future__ import annotations


class ReActBaseline:
    """ReAct agent baseline. History + tools, no drives/sleep/affect."""

    def __init__(self, history_window: int = 20):
        self.history_window = history_window
        self._conversation_history: list[str] = []

    def should_sleep(self, clock) -> bool:
        """ReAct baseline never sleeps."""
        return False

    def pre_cycle(self, drives: dict, engagement: dict, events: list):
        """Override drives to flat — ReAct has no internal motivation.

        But maintain conversation history for context.
        """
        # Flat drives — no internal state
        drives["social_hunger"] = 0.5
        drives["curiosity"] = 0.5
        drives["expression_need"] = 0.3
        drives["rest_need"] = 0.2
        drives["energy"] = 0.8
        drives["mood_valence"] = 0.0
        drives["mood_arousal"] = 0.3

        # Track conversation for history (ReAct has memory)
        for event in events:
            content = event.get("content", "")
            if content and event.get("event_type") in (
                "visitor_speech", "visitor_connect"
            ):
                self._conversation_history.append(content)
                # Trim to window
                if len(self._conversation_history) > self.history_window:
                    self._conversation_history = (
                        self._conversation_history[-self.history_window:]
                    )
