"""MemoryReader — grep-based keyword search over hot memory markdown files.

Primary recall mechanism for alive-memory.
Searches markdown files using simple keyword matching (no vector search).
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

# Common English stopwords that match too broadly in keyword grep
_STOPWORDS = frozenset({
    "the", "be", "to", "of", "and", "in", "that", "have", "it",
    "for", "not", "on", "with", "he", "as", "you", "do", "at",
    "this", "but", "his", "by", "from", "they", "we", "say", "her",
    "she", "or", "an", "will", "my", "one", "all", "would", "there",
    "their", "what", "so", "up", "out", "if", "about", "who", "get",
    "which", "go", "me", "when", "make", "can", "like", "no", "just",
    "him", "know", "take", "how", "come", "could", "them", "see",
    "than", "now", "look", "only", "into", "some", "time", "very",
    "your", "its", "our", "did", "had", "has", "was", "are", "were",
    "been", "being", "does", "also", "any", "may", "much",
})


class MemoryReader:
    """Grep-based reader for hot memory markdown files.

    Args:
        memory_dir: Root directory for hot memory files.
    """

    def __init__(self, memory_dir: str | Path) -> None:
        self._root = Path(memory_dir)

    @property
    def root(self) -> Path:
        return self._root

    def list_subdirs(self) -> list[str]:
        """List all existing subdirectory names dynamically."""
        if not self._root.is_dir():
            return []
        return sorted(d.name for d in self._root.iterdir() if d.is_dir())

    # ── Grep (primary recall) ────────────────────────────────────

    def grep_memory(
        self,
        query: str,
        *,
        subdirs: list[str] | None = None,
        limit: int = 20,
        context_lines: int = 3,
    ) -> list[dict[str, str]]:
        """Search all hot memory files for keywords.

        Returns matching passages ranked by keyword density and spread
        across source files for multi-session diversity.

        Args:
            query: Search keywords (space-separated).
            subdirs: Limit search to specific subdirs (e.g., ["journal", "visitors"]).
            limit: Max results to return.
            context_lines: Lines of context around each match.

        Returns:
            List of dicts with keys: file, line_num, match, context, subdir, score.
        """
        keywords = [
            kw.lower() for kw in query.split()
            if len(kw) >= 2 and kw.lower() not in _STOPWORDS
        ]
        if not keywords:
            return []

        search_dirs = subdirs or self.list_subdirs()
        candidates: list[dict] = []
        internal_cap = max(limit * 10, 200)

        for subdir in search_dirs:
            dir_path = self._root / subdir
            if not dir_path.is_dir():
                continue

            for md_file in sorted(dir_path.glob("**/*.md"), reverse=True):
                try:
                    lines = md_file.read_text(encoding="utf-8").splitlines()
                except (OSError, UnicodeDecodeError):
                    continue

                for i, line in enumerate(lines):
                    line_lower = line.lower()
                    if any(kw in line_lower for kw in keywords):
                        start = max(0, i - context_lines)
                        end = min(len(lines), i + context_lines + 1)
                        context = "\n".join(lines[start:end])
                        context_lower = context.lower()

                        # Score: fraction of distinct keywords present in context
                        hits = sum(1 for kw in keywords if kw in context_lower)
                        score = hits / len(keywords)

                        rel_file = str(md_file.relative_to(self._root))
                        candidates.append({
                            "file": rel_file,
                            "line_num": str(i + 1),
                            "match": line.strip(),
                            "context": context,
                            "subdir": subdir,
                            "score": score,
                        })

                        if len(candidates) >= internal_cap:
                            break
                if len(candidates) >= internal_cap:
                    break
            if len(candidates) >= internal_cap:
                break

        if not candidates:
            return []

        # Sort by score descending
        candidates.sort(key=lambda r: r["score"], reverse=True)

        # Diversity: round-robin across source files so results span sessions
        by_file: dict[str, list[dict]] = defaultdict(list)
        for c in candidates:
            by_file[c["file"]].append(c)

        results: list[dict] = []
        seen_contexts: set[str] = set()
        file_keys = list(by_file.keys())
        idx = 0
        while len(results) < limit and file_keys:
            key = file_keys[idx % len(file_keys)]
            bucket = by_file[key]
            if bucket:
                item = bucket.pop(0)
                # Deduplicate overlapping context windows
                if item["context"] not in seen_contexts:
                    seen_contexts.add(item["context"])
                    results.append(item)
            if not bucket:
                file_keys.remove(key)
                if file_keys:
                    idx = idx % len(file_keys)
            else:
                idx += 1

        return results

    # ── Visitor Notes ────────────────────────────────────────────

    def read_visitor(self, visitor_name: str) -> str | None:
        """Read all notes about a specific visitor.

        Returns the full content of the visitor's file, or None if not found.
        """
        safe_name = _safe_filename(visitor_name)
        filepath = self._root / "visitors" / f"{safe_name}.md"
        if filepath.is_file():
            return filepath.read_text(encoding="utf-8")
        return None

    def list_visitors(self) -> list[str]:
        """List all known visitors."""
        visitors_dir = self._root / "visitors"
        if not visitors_dir.is_dir():
            return []
        return [
            f.stem.replace("_", " ")
            for f in sorted(visitors_dir.glob("*.md"))
        ]

    # ── Journal ──────────────────────────────────────────────────

    def read_recent_journal(
        self,
        days: int = 3,
        max_entries: int = 10,
    ) -> list[str]:
        """Read recent journal entries.

        Returns entries from the last N days, most recent first.
        """
        journal_dir = self._root / "journal"
        if not journal_dir.is_dir():
            return []

        entries: list[str] = []
        # Journal files are named YYYY-MM-DD.md, sorted reverse = most recent first
        files = sorted(journal_dir.glob("*.md"), reverse=True)

        for filepath in files[:days]:
            try:
                content = filepath.read_text(encoding="utf-8")
                # Split into individual entries (separated by ## headers)
                sections = re.split(r"\n(?=## )", content)
                for section in sections:
                    section = section.strip()
                    if section and not section.startswith("# Journal"):
                        entries.append(section)
                        if len(entries) >= max_entries:
                            return entries
            except (OSError, UnicodeDecodeError):
                continue

        return entries

    # ── Self-Knowledge ───────────────────────────────────────────

    def read_self_knowledge(self, filename: str = "identity") -> str | None:
        """Read a self-knowledge file.

        Args:
            filename: Name of the self file (without .md extension).
        """
        safe_name = _safe_filename(filename)
        if not safe_name.endswith(".md"):
            safe_name += ".md"
        filepath = self._root / "self" / safe_name
        if filepath.is_file():
            return filepath.read_text(encoding="utf-8")
        return None

    def list_self_files(self) -> list[str]:
        """List all self-knowledge files."""
        self_dir = self._root / "self"
        if not self_dir.is_dir():
            return []
        return [f.stem for f in sorted(self_dir.glob("*.md"))]

    # ── Reflections ──────────────────────────────────────────────

    def read_recent_reflections(
        self,
        days: int = 3,
        max_entries: int = 5,
    ) -> list[str]:
        """Read recent reflections."""
        refl_dir = self._root / "reflections"
        if not refl_dir.is_dir():
            return []

        entries: list[str] = []
        files = sorted(refl_dir.glob("*.md"), reverse=True)

        for filepath in files[:days]:
            try:
                content = filepath.read_text(encoding="utf-8")
                sections = content.split("\n---\n")
                for section in sections:
                    section = section.strip()
                    if section and not section.startswith("# Reflections"):
                        entries.append(section)
                        if len(entries) >= max_entries:
                            return entries
            except (OSError, UnicodeDecodeError):
                continue

        return entries

    # ── Threads ──────────────────────────────────────────────────

    def read_thread(self, thread_id: str) -> str | None:
        """Read a conversation thread."""
        safe_id = _safe_filename(thread_id)
        filepath = self._root / "threads" / f"{safe_id}.md"
        if filepath.is_file():
            return filepath.read_text(encoding="utf-8")
        return None

    def list_threads(self) -> list[str]:
        """List all thread IDs."""
        threads_dir = self._root / "threads"
        if not threads_dir.is_dir():
            return []
        return [f.stem for f in sorted(threads_dir.glob("*.md"))]


def _safe_filename(name: str) -> str:
    safe = name.lower().strip()
    safe = safe.replace(" ", "_")
    safe = "".join(c for c in safe if c.isalnum() or c in ("_", "-", "."))
    return safe or "unnamed"
