"""MCP (Model Context Protocol) server adapter for alive-memory.

Exposes alive-memory operations as MCP tools that Claude Code
and other MCP-compatible clients can call directly.

Requires: pip install alive-memory[mcp]

Usage (stdio transport — for Claude Code):
    alive-memory-mcp

    # Or with configuration:
    ALIVE_DB=my_agent.db alive-memory-mcp

Claude Code settings.json:
    {
        "mcpServers": {
            "alive-memory": {
                "command": "alive-memory-mcp",
                "env": {"ALIVE_DB": "memory.db"}
            }
        }
    }
"""

from __future__ import annotations

import json
import os

from mcp.server.fastmcp import FastMCP

from alive_memory import AliveMemory

mcp = FastMCP("alive-memory")

_memory: AliveMemory | None = None


async def _get_memory() -> AliveMemory:
    """Lazily initialize the AliveMemory instance."""
    global _memory  # noqa: PLW0603
    if _memory is None:
        db_path = os.getenv("ALIVE_DB", "memory.db")
        config_path = os.getenv("ALIVE_CONFIG") or None
        memory_dir = os.getenv("ALIVE_MEMORY_DIR", "memory_hot")
        _memory = AliveMemory(
            storage=db_path,
            memory_dir=memory_dir,
            config=config_path,
        )
        await _memory.initialize()
    return _memory


@mcp.tool()
async def memory_intake(event_type: str, content: str) -> str:
    """Record an event into the agent's memory.

    The event passes through salience gating — only significant events
    become memories. Returns whether the event was recorded.

    Args:
        event_type: Type of event. One of: conversation, action, observation, system.
        content: The event content/text to remember.
    """
    memory = await _get_memory()
    moment = await memory.intake(event_type=event_type, content=content)
    if moment is None:
        return json.dumps({"recorded": False, "reason": "Below salience threshold"})
    return json.dumps({
        "recorded": True,
        "id": moment.id,
        "salience": round(moment.salience, 3),
        "valence": round(moment.valence, 3),
    })


@mcp.tool()
async def memory_recall(query: str, limit: int = 10) -> str:
    """Search the agent's memory for information relevant to a query.

    Returns categorized results from journal entries, visitor notes,
    self-knowledge, and reflections.

    Args:
        query: Keywords to search for in memory.
        limit: Maximum results per category (default 10).
    """
    memory = await _get_memory()
    ctx = await memory.recall(query=query, limit=limit)
    return json.dumps({
        "query": ctx.query,
        "total_hits": ctx.total_hits,
        "journal_entries": ctx.journal_entries,
        "visitor_notes": ctx.visitor_notes,
        "self_knowledge": ctx.self_knowledge,
        "reflections": ctx.reflections,
    })


@mcp.tool()
async def memory_state() -> str:
    """Get the agent's current cognitive state.

    Returns mood (valence, arousal, word label), energy level,
    drive levels (curiosity, social, expression, rest), and memory statistics.
    """
    memory = await _get_memory()
    state = await memory.get_state()
    return json.dumps({
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
    })


@mcp.tool()
async def memory_consolidate(depth: str = "nap") -> str:
    """Trigger memory consolidation (sleep cycle).

    Processes recent moments into long-term memory with reflections
    and dreaming. Use 'nap' for light consolidation, 'full' for deep sleep.

    Args:
        depth: Consolidation depth — 'nap' or 'full'.
    """
    memory = await _get_memory()
    report = await memory.consolidate(depth=depth)
    return json.dumps({
        "moments_processed": report.moments_processed,
        "journal_entries_written": report.journal_entries_written,
        "dreams": report.dreams,
        "depth": report.depth,
    })


def main() -> None:
    """CLI entry point: alive-memory-mcp."""
    mcp.run()


if __name__ == "__main__":
    main()
