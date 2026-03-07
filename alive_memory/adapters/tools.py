"""Generic tool definitions for agent framework integration.

Provides JSON-schema tool definitions that any agent framework can consume.
Also provides async executor functions that call AliveMemory methods.

Supported frameworks:
- Google ADK (via alive_memory.adapters.adk)
- LangGraph (via alive_memory.adapters.langgraph)
- Any framework that accepts JSON schema tool definitions

Usage:
    from alive_memory.adapters.tools import TOOL_DEFINITIONS, execute_tool

    # Get tool schemas for your framework
    for tool in TOOL_DEFINITIONS:
        register_tool(tool["name"], tool["description"], tool["parameters"])

    # Execute a tool call
    result = await execute_tool(memory, "recall", {"query": "hello"})
"""

from __future__ import annotations

from typing import Any

from alive_memory import AliveMemory

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "memory_intake",
        "description": (
            "Record an event into the agent's memory. The event passes through "
            "salience gating — only significant events become memories. "
            "Returns the memory moment if recorded, null if below threshold."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "event_type": {
                    "type": "string",
                    "enum": ["conversation", "action", "observation", "system"],
                    "description": "Type of event being recorded.",
                },
                "content": {
                    "type": "string",
                    "description": "The event content/text to remember.",
                },
            },
            "required": ["event_type", "content"],
        },
    },
    {
        "name": "memory_recall",
        "description": (
            "Search the agent's memory for information relevant to a query. "
            "Returns categorized results from journal entries, visitor notes, "
            "self-knowledge, and reflections."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keywords to search for in memory.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results per category (default 10).",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_state",
        "description": (
            "Get the agent's current cognitive state including mood "
            "(valence/arousal), energy level, drive levels "
            "(curiosity, social, expression, rest), and memory statistics."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "memory_consolidate",
        "description": (
            "Trigger memory consolidation (sleep cycle). Processes recent "
            "moments into long-term memory with reflections and dreaming. "
            "Use 'nap' for light consolidation, 'full' for deep sleep."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "depth": {
                    "type": "string",
                    "enum": ["full", "nap"],
                    "description": "Consolidation depth (default: nap).",
                    "default": "nap",
                },
            },
        },
    },
]


async def execute_tool(
    memory: AliveMemory,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Execute a tool call against an AliveMemory instance.

    Args:
        memory: The AliveMemory instance.
        tool_name: Name of the tool to execute.
        arguments: Tool arguments.

    Returns:
        Result dict suitable for returning to the agent framework.

    Raises:
        ValueError: If tool_name is unknown.
    """
    if tool_name == "memory_intake":
        moment = await memory.intake(
            event_type=arguments["event_type"],
            content=arguments["content"],
        )
        if moment is None:
            return {"recorded": False, "reason": "Below salience threshold"}
        return {
            "recorded": True,
            "id": moment.id,
            "salience": moment.salience,
            "valence": moment.valence,
        }

    if tool_name == "memory_recall":
        ctx = await memory.recall(
            query=arguments["query"],
            limit=arguments.get("limit", 10),
        )
        return {
            "query": ctx.query,
            "total_hits": ctx.total_hits,
            "journal_entries": ctx.journal_entries,
            "visitor_notes": ctx.visitor_notes,
            "self_knowledge": ctx.self_knowledge,
            "reflections": ctx.reflections,
        }

    if tool_name == "memory_state":
        state = await memory.get_state()
        return {
            "mood": {
                "valence": state.mood.valence,
                "arousal": state.mood.arousal,
                "word": state.mood.word,
            },
            "energy": state.energy,
            "drives": {
                "curiosity": state.drives.curiosity,
                "social": state.drives.social,
                "expression": state.drives.expression,
                "rest": state.drives.rest,
            },
            "cycle_count": state.cycle_count,
            "memories_total": state.memories_total,
        }

    if tool_name == "memory_consolidate":
        report = await memory.consolidate(
            depth=arguments.get("depth", "nap"),
        )
        return {
            "moments_processed": report.moments_processed,
            "journal_entries_written": report.journal_entries_written,
            "dreams": report.dreams,
            "depth": report.depth,
        }

    raise ValueError(f"Unknown tool: {tool_name!r}")
