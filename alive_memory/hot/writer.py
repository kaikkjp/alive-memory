"""MemoryWriter — append-only writes to hot memory markdown files.

Tier 2 of the three-tier memory architecture.
All writes are append-only (no overwrites except self-knowledge files).
Directory structure is created on first use.

All content is passed through scrub_numbers() before writing to prevent
raw numeric state (valence=0.84, 73%, etc.) from leaking into conscious
memory. Dates and times are preserved.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from alive_memory.hot.translator import scrub_numbers


class MemoryWriter:
    """Append-only writer for hot memory markdown files.

    Args:
        memory_dir: Root directory for hot memory files (e.g., /data/agent/memory).
    """

    SUBDIRS = [
        "journal",
        "visitors",
        "threads",
        "reflections",
        "self",
        "collection",
    ]

    def __init__(self, memory_dir: str | Path) -> None:
        self._root = Path(memory_dir)
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        for subdir in self.SUBDIRS:
            (self._root / subdir).mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    # ── Journal ──────────────────────────────────────────────────

    def append_journal(
        self,
        content: str,
        *,
        date: Optional[datetime] = None,
        moment_id: Optional[str] = None,
    ) -> Path:
        """Append a journal entry for the given date.

        Each day gets its own file: journal/YYYY-MM-DD.md
        Entries are appended with timestamps.
        """
        ts = date or datetime.now(timezone.utc)
        date_str = ts.strftime("%Y-%m-%d")
        filepath = self._root / "journal" / f"{date_str}.md"

        time_str = ts.strftime("%H:%M")
        header = f"\n## {time_str}"
        if moment_id:
            header += f" [{moment_id[:8]}]"
        header += "\n\n"

        with open(filepath, "a", encoding="utf-8") as f:
            if os.path.getsize(filepath) == 0 if filepath.exists() else True:
                f.write(f"# Journal — {date_str}\n")
            f.write(header)
            f.write(scrub_numbers(content.strip()))
            f.write("\n")

        return filepath

    # ── Visitors ─────────────────────────────────────────────────

    def append_visitor(
        self,
        visitor_name: str,
        content: str,
        *,
        timestamp: Optional[datetime] = None,
    ) -> Path:
        """Append a note about a visitor/person.

        Each visitor gets their own file: visitors/{name}.md
        """
        safe_name = _safe_filename(visitor_name)
        filepath = self._root / "visitors" / f"{safe_name}.md"
        ts = timestamp or datetime.now(timezone.utc)
        time_str = ts.strftime("%Y-%m-%d %H:%M")

        with open(filepath, "a", encoding="utf-8") as f:
            if not filepath.exists() or os.path.getsize(filepath) == 0:
                f.write(f"# {visitor_name}\n\n")
            f.write(f"\n### {time_str}\n\n")
            f.write(scrub_numbers(content.strip()))
            f.write("\n")

        return filepath

    # ── Reflections ──────────────────────────────────────────────

    def append_reflection(
        self,
        content: str,
        *,
        date: Optional[datetime] = None,
        label: str = "",
    ) -> Path:
        """Append a reflection from consolidation.

        One file per day: reflections/YYYY-MM-DD.md
        """
        ts = date or datetime.now(timezone.utc)
        date_str = ts.strftime("%Y-%m-%d")
        filepath = self._root / "reflections" / f"{date_str}.md"

        with open(filepath, "a", encoding="utf-8") as f:
            if not filepath.exists() or os.path.getsize(filepath) == 0:
                f.write(f"# Reflections — {date_str}\n")
            header = f"\n---\n"
            if label:
                header += f"**{label}**\n\n"
            f.write(header)
            f.write(scrub_numbers(content.strip()))
            f.write("\n")

        return filepath

    # ── Threads ──────────────────────────────────────────────────

    def append_thread(
        self,
        thread_id: str,
        content: str,
        *,
        timestamp: Optional[datetime] = None,
    ) -> Path:
        """Append context to a conversation thread.

        Each thread gets its own file: threads/{thread_id}.md
        """
        safe_id = _safe_filename(thread_id)
        filepath = self._root / "threads" / f"{safe_id}.md"
        ts = timestamp or datetime.now(timezone.utc)
        time_str = ts.strftime("%Y-%m-%d %H:%M")

        with open(filepath, "a", encoding="utf-8") as f:
            if not filepath.exists() or os.path.getsize(filepath) == 0:
                f.write(f"# Thread {thread_id}\n\n")
            f.write(f"\n### {time_str}\n\n")
            f.write(scrub_numbers(content.strip()))
            f.write("\n")

        return filepath

    # ── Self-Knowledge ───────────────────────────────────────────

    def write_self_file(
        self,
        filename: str,
        content: str,
    ) -> Path:
        """Write (overwrite) a self-knowledge file.

        These are the only non-append files. Used for:
          self/identity.md, self/preferences.md, self/relationships.md, etc.
        """
        safe_name = _safe_filename(filename)
        if not safe_name.endswith(".md"):
            safe_name += ".md"
        filepath = self._root / "self" / safe_name

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(scrub_numbers(content))

        return filepath

    # ── Collection ───────────────────────────────────────────────

    def append_collection(
        self,
        item_name: str,
        content: str,
    ) -> Path:
        """Append to a collection file.

        Collection items: collection/{item_name}.md
        """
        safe_name = _safe_filename(item_name)
        filepath = self._root / "collection" / f"{safe_name}.md"

        with open(filepath, "a", encoding="utf-8") as f:
            if not filepath.exists() or os.path.getsize(filepath) == 0:
                f.write(f"# {item_name}\n\n")
            f.write(scrub_numbers(content.strip()))
            f.write("\n\n")

        return filepath


def _safe_filename(name: str) -> str:
    """Convert a string to a safe filename."""
    safe = name.lower().strip()
    safe = safe.replace(" ", "_")
    # Keep only alphanumeric, underscore, hyphen, dot
    safe = "".join(c for c in safe if c.isalnum() or c in ("_", "-", "."))
    return safe or "unnamed"
