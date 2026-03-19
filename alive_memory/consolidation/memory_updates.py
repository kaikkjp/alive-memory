"""Memory updates — apply LLM reflection outputs to hot memory.

After the LLM reflects on a day moment (with hot context + cold echoes),
this module writes the reflection outputs to the appropriate hot memory files.

Write-once policy:
  - Journal: full reflection text (canonical hot narrative)
  - Visitor: one-line summary + reference to journal entry
  - Thread: one-line summary + reference to journal entry
  - Dynamic category: one-line index entry + reference

This prevents duplicate full-text copies that inflate grep recall
with fake evidence strength.
"""

from __future__ import annotations

import logging

from alive_memory.hot.writer import MemoryWriter
from alive_memory.types import DayMoment

logger = logging.getLogger(__name__)


def _make_reference(moment_id: str, summary: str | None = None) -> str:
    """Build a short reference line pointing to the journal entry."""
    short_id = moment_id[:8] if moment_id else "????????"
    if summary:
        return f"{summary} — see journal [{short_id}]"
    return f"See journal [{short_id}]"


def _one_line_summary(text: str, max_len: int = 80) -> str:
    """Extract a one-line summary from reflection text."""
    # Take first sentence (up to first period, question mark, or exclamation)
    for i, ch in enumerate(text):
        if ch in ".!?" and i > 10:
            line = text[: i + 1].strip()
            if len(line) <= max_len:
                return line
            return line[:max_len - 1] + "…"
    # No sentence boundary — truncate
    line = text.strip().split("\n")[0]
    if len(line) <= max_len:
        return line
    return line[:max_len - 1] + "…"


def apply_reflection_to_hot_memory(
    moment: DayMoment,
    reflection_text: str,
    writer: MemoryWriter,
    *,
    visitor_name: str | None = None,
    thread_id: str | None = None,
    self_updates: dict[str, str] | None = None,
    categories: list[str] | None = None,
) -> dict[str, int]:
    """Apply a reflection's outputs to hot memory files.

    Writes full text to journal only. Visitor, thread, and dynamic
    categories get a one-line summary + reference to avoid duplication.

    Args:
        moment: The original day moment.
        reflection_text: LLM-generated reflection about the moment.
        writer: MemoryWriter for hot memory.
        visitor_name: If the moment involved a visitor, record notes about them.
        thread_id: If the moment is part of a thread, append thread context.
        self_updates: Dict of self-knowledge file → content to write.
        categories: LLM-returned category names for dynamic routing.

    Returns:
        Dict counting writes by type: {journal: N, visitor: N, ...}
    """
    counts: dict[str, int] = {"journal": 0, "visitor": 0, "thread": 0, "self": 0, "dynamic": 0}

    # Always write full text to journal (canonical copy)
    writer.append_journal(
        reflection_text,
        date=moment.timestamp,
        moment_id=moment.id,
    )
    counts["journal"] = 1

    # Build short reference for non-journal destinations (computed once)
    ref = _make_reference(moment.id, _one_line_summary(reflection_text))

    # Write visitor reference (not full text)
    if visitor_name:
        writer.append_visitor(
            visitor_name,
            ref,
            timestamp=moment.timestamp,
        )
        counts["visitor"] = 1

    # Append thread reference (not full text)
    if thread_id:
        writer.append_thread(
            thread_id,
            ref,
            timestamp=moment.timestamp,
        )
        counts["thread"] = 1

    # Update self-knowledge files if reflection produced self-insights
    if self_updates:
        for filename, content in self_updates.items():
            writer.write_self_file(filename, content)
            counts["self"] += 1

    # Write to dynamic categories (short index entry, not full text)
    _legacy = {"journal", "visitors", "threads", "reflections", "self", "collection"}
    if categories:
        for cat in categories:
            if not cat or cat.lower() in _legacy:
                continue
            try:
                writer.append_to_category(
                    cat,
                    ref,
                    timestamp=moment.timestamp,
                )
                counts["dynamic"] += 1
            except ValueError:
                logger.debug("Skipping invalid category %r", cat)

    return counts
