"""Memory reader — grep-based recall from conscious memory (MD files).

Searches Markdown files by keyword, returns {label, content} dicts matching
the hippocampus recall interface.  Falls back gracefully when files don't
exist yet.
"""

import asyncio
import os
import re

import clock


class MemoryReader:
    """Grep-based reader for conscious memory MD files."""

    def __init__(self, root: str = None):
        self.root = root or os.getenv('MEMORY_ROOT', 'data/memory')

    def _path(self, *parts: str) -> str:
        return os.path.join(self.root, *parts)

    def _read_file(self, path: str) -> str | None:
        """Read a file, return None if it doesn't exist."""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except (FileNotFoundError, PermissionError):
            return None

    def _split_sections(self, text: str) -> list[str]:
        """Split markdown text into sections by ## headers."""
        if not text:
            return []
        sections = re.split(r'(?=^## )', text, flags=re.MULTILINE)
        return [s.strip() for s in sections if s.strip()]

    def _truncate(self, text: str, max_chars: int) -> str:
        """Truncate text to max_chars, cutting at last newline."""
        if len(text) <= max_chars:
            return text
        truncated = text[:max_chars]
        last_nl = truncated.rfind('\n')
        if last_nl > max_chars // 2:
            truncated = truncated[:last_nl]
        return truncated + '...'

    def _match_keywords(self, text: str, query: str) -> bool:
        """Check if text contains any query keywords (> 3 chars)."""
        words = [w for w in query.lower().split() if len(w) > 3]
        if not words:
            return True  # empty query matches everything
        text_lower = text.lower()
        return any(w in text_lower for w in words)

    async def grep_memory(self, query: str, directories: list[str] = None,
                          max_results: int = 5, max_chars: int = 800) -> list[dict]:
        """Search MD files for query keywords.

        Returns list of {label, content} dicts sorted by recency.
        """
        if directories is None:
            directories = ['journal', 'visitors', 'reflections', 'browse',
                           'threads', 'collection']

        results = []
        for dir_name in directories:
            dir_path = self._path(dir_name)
            if not os.path.isdir(dir_path):
                continue

            # Get MD files sorted by modification time (newest first)
            try:
                files = sorted(
                    [f for f in os.listdir(dir_path) if f.endswith('.md')],
                    key=lambda f: os.path.getmtime(os.path.join(dir_path, f)),
                    reverse=True,
                )
            except OSError:
                continue

            for filename in files[:10]:  # cap file scan per directory
                filepath = os.path.join(dir_path, filename)
                text = await asyncio.to_thread(self._read_file, filepath)
                if not text:
                    continue

                sections = self._split_sections(text)
                for section in reversed(sections):  # newest sections last in file
                    if self._match_keywords(section, query):
                        results.append({
                            'label': f'{dir_name}/{filename}',
                            'content': self._truncate(section, max_chars),
                            '_mtime': os.path.getmtime(filepath),
                        })
                        if len(results) >= max_results * 3:
                            break

                if len(results) >= max_results * 3:
                    break

        # Sort by recency, limit results
        results.sort(key=lambda r: r.get('_mtime', 0), reverse=True)
        for r in results:
            r.pop('_mtime', None)
        return results[:max_results]

    async def read_visitor(self, source_key: str,
                           max_chars: int = 600) -> dict | None:
        """Read a visitor's memory file, returning the most recent entries.

        Returns {label, content} or None if no file exists.
        """
        if not source_key:
            return None
        path = self._path('visitors', f'{source_key}.md')
        text = await asyncio.to_thread(self._read_file, path)
        if not text:
            return None

        # Extract visitor name from header
        name = source_key
        header_match = re.match(r'^# Visitor: (.+)', text)
        if header_match:
            name = header_match.group(1).strip()

        # Take the tail (most recent entries)
        tail = self._truncate(text[-max_chars:] if len(text) > max_chars else text,
                              max_chars)
        return {
            'label': f'Memory of {name}',
            'content': tail,
        }

    async def read_recent_journal(self, days: int = 1,
                                  max_entries: int = 3) -> list[dict]:
        """Read recent journal entries.

        Returns list of {label, content} dicts.
        """
        results = []
        now = clock.now()

        for day_offset in range(days + 1):  # today + yesterday if days=1
            from datetime import timedelta
            target_date = now - timedelta(days=day_offset)
            date_str = target_date.strftime('%Y-%m-%d')
            path = self._path('journal', f'{date_str}.md')
            text = await asyncio.to_thread(self._read_file, path)
            if not text:
                continue

            sections = self._split_sections(text)
            # Take the most recent entries (at the end of the file)
            for section in reversed(sections[-max_entries:]):
                results.append({
                    'label': 'Recent thoughts',
                    'content': self._truncate(section, 400),
                })
                if len(results) >= max_entries:
                    break
            if len(results) >= max_entries:
                break

        return results

    async def read_day_context(self, max_entries: int = 3) -> list[dict]:
        """Read today's journal for 'earlier today' context.

        Returns list of {label, content} dicts.
        """
        now = clock.now()
        date_str = now.strftime('%Y-%m-%d')
        path = self._path('journal', f'{date_str}.md')
        text = await asyncio.to_thread(self._read_file, path)
        if not text:
            return []

        sections = self._split_sections(text)
        results = []
        # Take earliest entries as "earlier today" context
        for section in sections[:max_entries]:
            results.append({
                'label': 'Earlier today',
                'content': self._truncate(section, 400),
            })

        return results

    async def read_self_knowledge(self) -> dict | None:
        """Read self-knowledge files (identity.md + traits.md).

        Returns {label, content} or None if no files exist.
        """
        parts = []

        for filename in ('identity.md', 'traits.md'):
            path = self._path('self', filename)
            text = await asyncio.to_thread(self._read_file, path)
            if text:
                parts.append(text.strip())

        if not parts:
            return None

        return {
            'label': 'Things I know about myself',
            'content': self._truncate('\n\n'.join(parts), 600),
        }

    async def read_collection(self, query: str = '') -> list[dict]:
        """Search the collection catalog.

        Returns list of {label, content} dicts.
        """
        path = self._path('collection', 'catalog.md')
        text = await asyncio.to_thread(self._read_file, path)
        if not text:
            return []

        if query:
            # Filter lines matching query keywords
            lines = text.split('\n')
            matching = [l for l in lines if self._match_keywords(l, query)]
            if matching:
                return [{
                    'label': 'Related items in my collection',
                    'content': self._truncate('\n'.join(matching), 400),
                }]
            return []

        return [{
            'label': 'My collection',
            'content': self._truncate(text, 400),
        }]

    async def read_threads(self, max_items: int = 3) -> list[dict]:
        """Read active thought threads.

        Returns list of {label, content} dicts.
        """
        dir_path = self._path('threads')
        if not os.path.isdir(dir_path):
            return []

        try:
            files = sorted(
                [f for f in os.listdir(dir_path) if f.endswith('.md')],
                key=lambda f: os.path.getmtime(os.path.join(dir_path, f)),
                reverse=True,
            )
        except OSError:
            return []

        results = []
        for filename in files[:max_items]:
            filepath = os.path.join(dir_path, filename)
            text = await asyncio.to_thread(self._read_file, filepath)
            if text:
                # Get last section as most recent thought
                sections = self._split_sections(text)
                last = sections[-1] if sections else text
                results.append({
                    'label': f'Thread: {filename[:-3]}',  # strip .md
                    'content': self._truncate(last, 300),
                })

        return results


# ── Module singleton ──

_instance: MemoryReader | None = None


def get_memory_reader() -> MemoryReader:
    """Get or create the global MemoryReader instance."""
    global _instance
    if _instance is None:
        _instance = MemoryReader()
    return _instance


def reset_memory_reader() -> None:
    """Reset the singleton (for tests)."""
    global _instance
    _instance = None
