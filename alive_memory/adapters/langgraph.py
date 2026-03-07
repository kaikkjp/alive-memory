"""LangGraph adapter for alive-memory.

Exposes alive-memory operations as LangChain tools compatible with
LangGraph's ToolNode.

Requires: pip install langchain-core

Usage:
    from alive_memory import AliveMemory
    from alive_memory.adapters.langgraph import create_langgraph_tools

    memory = AliveMemory(storage="memory.db", memory_dir="/data/agent/memory")
    await memory.initialize()

    tools = create_langgraph_tools(memory)
    # Use with LangGraph ToolNode:
    from langgraph.prebuilt import ToolNode
    tool_node = ToolNode(tools)
"""

from __future__ import annotations

import json

from alive_memory import AliveMemory


def create_langgraph_tools(memory: AliveMemory) -> list:
    """Create LangChain-compatible tools for use in LangGraph.

    Returns:
        List of StructuredTool instances.
    """
    from langchain_core.tools import StructuredTool

    async def _intake(event_type: str, content: str) -> str:
        moment = await memory.intake(event_type=event_type, content=content)
        if moment is None:
            return json.dumps({"recorded": False, "reason": "Below salience threshold"})
        return json.dumps({
            "recorded": True,
            "id": moment.id,
            "salience": round(moment.salience, 3),
        })

    async def _recall(query: str, limit: int = 10) -> str:
        ctx = await memory.recall(query=query, limit=limit)
        return json.dumps({
            "total_hits": ctx.total_hits,
            "journal_entries": ctx.journal_entries,
            "visitor_notes": ctx.visitor_notes,
            "self_knowledge": ctx.self_knowledge,
            "reflections": ctx.reflections,
        })

    async def _state() -> str:
        state = await memory.get_state()
        return json.dumps({
            "mood": {"valence": state.mood.valence, "arousal": state.mood.arousal},
            "energy": state.energy,
            "drives": {
                "curiosity": state.drives.curiosity,
                "social": state.drives.social,
                "expression": state.drives.expression,
                "rest": state.drives.rest,
            },
        })

    async def _consolidate(depth: str = "nap") -> str:
        report = await memory.consolidate(depth=depth)
        return json.dumps({
            "moments_processed": report.moments_processed,
            "journal_entries_written": report.journal_entries_written,
            "dreams": report.dreams,
        })

    return [
        StructuredTool.from_function(
            coroutine=_intake,
            name="memory_intake",
            description=(
                "Record an event into the agent's memory. Only significant events "
                "pass salience gating and become memories."
            ),
        ),
        StructuredTool.from_function(
            coroutine=_recall,
            name="memory_recall",
            description=(
                "Search the agent's memory for information. Returns journal entries, "
                "visitor notes, self-knowledge, and reflections."
            ),
        ),
        StructuredTool.from_function(
            coroutine=_state,
            name="memory_state",
            description="Get the agent's current cognitive state: mood, energy, drives.",
        ),
        StructuredTool.from_function(
            coroutine=_consolidate,
            name="memory_consolidate",
            description=(
                "Trigger memory consolidation. 'nap' for light, 'full' for deep."
            ),
        ),
    ]
