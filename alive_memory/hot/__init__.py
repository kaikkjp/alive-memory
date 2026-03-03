"""Hot memory (Tier 2) — markdown files on disk.

The primary recall mechanism. Grep over markdown, not vector search.

Subdirectories:
  memory/journal/      — daily journal entries from consolidation
  memory/visitors/     — notes about visitors/people
  memory/threads/      — conversation thread context
  memory/reflections/  — self-reflections from consolidation
  memory/self/         — self-knowledge files
  memory/collection/   — collected items, interesting things
"""

from alive_memory.hot.reader import MemoryReader
from alive_memory.hot.writer import MemoryWriter

__all__ = ["MemoryReader", "MemoryWriter"]
