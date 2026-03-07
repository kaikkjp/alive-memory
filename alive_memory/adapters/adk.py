"""Google ADK (Agent Development Kit) adapter for alive-memory.

Exposes alive-memory operations as ADK-compatible tool functions
that can be added to an ADK Agent.

Requires: pip install google-adk

Usage:
    from alive_memory import AliveMemory
    from alive_memory.adapters.adk import create_adk_tools
    from google.adk import Agent

    memory = AliveMemory(storage="memory.db", memory_dir="/data/agent/memory")
    await memory.initialize()

    tools = create_adk_tools(memory)
    agent = Agent(name="my_agent", tools=tools, ...)
"""

from __future__ import annotations

from typing import Any

from alive_memory import AliveMemory


def create_adk_tools(memory: AliveMemory) -> list:
    """Create ADK-compatible tool functions bound to an AliveMemory instance.

    ADK uses function signatures and docstrings to generate tool schemas,
    so each function has explicit typed parameters and detailed docstrings.

    Returns:
        List of async functions suitable for passing to Agent(tools=[...]).
    """

    async def memory_intake(
        event_type: str,
        content: str,
    ) -> dict[str, Any]:
        """Record an event into the agent's memory.

        The event passes through salience gating — only significant events
        become memories. Returns whether the event was recorded.

        Args:
            event_type: Type of event. One of: conversation, action, observation, system.
            content: The event content/text to remember.
        """
        moment = await memory.intake(event_type=event_type, content=content)
        if moment is None:
            return {"recorded": False, "reason": "Below salience threshold"}
        return {
            "recorded": True,
            "id": moment.id,
            "salience": round(moment.salience, 3),
            "valence": round(moment.valence, 3),
        }

    async def memory_recall(
        query: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search the agent's memory for information relevant to a query.

        Returns categorized results from journal entries, visitor notes,
        self-knowledge, and reflections.

        Args:
            query: Keywords to search for in memory.
            limit: Maximum results per category.
        """
        ctx = await memory.recall(query=query, limit=limit)
        return {
            "query": ctx.query,
            "total_hits": ctx.total_hits,
            "journal_entries": ctx.journal_entries,
            "visitor_notes": ctx.visitor_notes,
            "self_knowledge": ctx.self_knowledge,
            "reflections": ctx.reflections,
        }

    async def memory_state() -> dict[str, Any]:
        """Get the agent's current cognitive state.

        Returns mood (valence, arousal), energy, drive levels
        (curiosity, social, expression, rest), and memory statistics.
        """
        state = await memory.get_state()
        return {
            "mood": {
                "valence": round(state.mood.valence, 3),
                "arousal": round(state.mood.arousal, 3),
                "word": state.mood.word,
            },
            "energy": round(state.energy, 3),
            "drives": {
                "curiosity": round(state.drives.curiosity, 3),
                "social": round(state.drives.social, 3),
                "expression": round(state.drives.expression, 3),
                "rest": round(state.drives.rest, 3),
            },
            "cycle_count": state.cycle_count,
            "memories_total": state.memories_total,
        }

    async def memory_consolidate(
        depth: str = "nap",
    ) -> dict[str, Any]:
        """Trigger memory consolidation (sleep cycle).

        Processes recent moments into long-term memory with reflections
        and dreaming. Use 'nap' for light, 'full' for deep consolidation.

        Args:
            depth: Consolidation depth — 'nap' or 'full'.
        """
        report = await memory.consolidate(depth=depth)
        return {
            "moments_processed": report.moments_processed,
            "journal_entries_written": report.journal_entries_written,
            "dreams": report.dreams,
            "depth": report.depth,
        }

    return [memory_intake, memory_recall, memory_state, memory_consolidate]
