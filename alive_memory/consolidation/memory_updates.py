"""Memory updates — apply LLM reflection outputs to hot memory.

After the LLM reflects on a day moment (with hot context + cold echoes),
this module writes the reflection outputs to the appropriate hot memory files.
"""

from __future__ import annotations

from alive_memory.hot.writer import MemoryWriter
from alive_memory.types import DayMoment


def apply_reflection_to_hot_memory(
    moment: DayMoment,
    reflection_text: str,
    writer: MemoryWriter,
    *,
    visitor_name: str | None = None,
    thread_id: str | None = None,
    self_updates: dict[str, str] | None = None,
) -> dict[str, int]:
    """Apply a reflection's outputs to hot memory files.

    Writes to journal, visitors, threads, self-knowledge as appropriate.

    Args:
        moment: The original day moment.
        reflection_text: LLM-generated reflection about the moment.
        writer: MemoryWriter for hot memory.
        visitor_name: If the moment involved a visitor, record notes about them.
        thread_id: If the moment is part of a thread, append thread context.
        self_updates: Dict of self-knowledge file → content to write.

    Returns:
        Dict counting writes by type: {journal: N, visitor: N, ...}
    """
    counts = {"journal": 0, "visitor": 0, "thread": 0, "self": 0}

    # Always write a journal entry
    writer.append_journal(
        reflection_text,
        date=moment.timestamp,
        moment_id=moment.id,
    )
    counts["journal"] = 1

    # Write visitor notes if applicable
    if visitor_name:
        writer.append_visitor(
            visitor_name,
            reflection_text,
            timestamp=moment.timestamp,
        )
        counts["visitor"] = 1

    # Append to thread if applicable
    if thread_id:
        writer.append_thread(
            thread_id,
            reflection_text,
            timestamp=moment.timestamp,
        )
        counts["thread"] = 1

    # Update self-knowledge files if reflection produced self-insights
    if self_updates:
        for filename, content in self_updates.items():
            writer.write_self_file(filename, content)
            counts["self"] += 1

    return counts
