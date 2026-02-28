"""Memory writer — append-only conscious memory layer (MD files).

Writes experiential, natural-language entries to Markdown files.  No raw
numbers, no percentages, no drive names — every write passes through
scrub_numbers() before touching disk.

Waking mode: append only (no editing past entries, no deletions).
Sleep mode: write_self_file() and annotate() additionally available.
Enforcement is at the call site, not here.
"""

import os
import re

import clock
from memory_translator import scrub_numbers
from runtime_context import get_cycle_context, hash_text, resolve_cycle_id


_MEMORY_DIRS = [
    'journal',
    'visitors',
    'reflections',
    'browse',
    'self',
    'threads',
    'collection',
]


def _estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / 4))


def _infer_source() -> str:
    return 'awake' if get_cycle_context() else 'sleep'


class MemoryWriter:
    """Append-only file writer for conscious memory."""

    def __init__(self, root: str = None):
        self.root = root or os.getenv('MEMORY_ROOT', 'data/memory')

    def ensure_dirs(self) -> None:
        """Create the memory directory tree (idempotent)."""
        for d in _MEMORY_DIRS:
            os.makedirs(os.path.join(self.root, d), exist_ok=True)

    def _path(self, *parts: str) -> str:
        """Build a path under the memory root."""
        return os.path.join(self.root, *parts)

    def _safe_write(self, path: str, text: str, mode: str = 'a') -> None:
        """Write text to file, creating parent dirs if needed.

        Always scrubs numbers before writing.
        """
        clean = scrub_numbers(text)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode, encoding='utf-8') as f:
            f.write(clean)

    async def _log_write(self, *, memory_type: str, source: str,
                         text: str, location: str, payload: dict | None = None,
                         sleep_session_id: str | None = None) -> None:
        """Best-effort structured write log for evidence pack generation."""
        try:
            from db.analytics import log_memory_write

            clean = scrub_numbers(text or "")
            await log_memory_write(
                memory_type=memory_type,
                source=source,
                content_hash=hash_text(clean),
                tokens_written=_estimate_tokens(clean),
                size_bytes=len(clean.encode('utf-8')),
                cycle_id=resolve_cycle_id(None),
                sleep_session_id=sleep_session_id,
                location=location,
                payload=payload or {},
            )
        except Exception:
            return

    async def append_journal(self, text: str, mood_desc: str = None,
                             tags: list[str] = None) -> None:
        """Append an entry to today's journal file.

        File: journal/{date}.md
        """
        if not text:
            return
        now = clock.now()
        date_str = now.strftime('%Y-%m-%d')
        time_str = now.strftime('%H:%M')

        entry = f'\n## {time_str}\n\n{text.strip()}\n'
        if mood_desc:
            entry += f'\nmood: {mood_desc}\n'
        if tags:
            entry += f'tags: {", ".join(tags)}\n'

        path = self._path('journal', f'{date_str}.md')
        self._safe_write(path, entry)
        await self._log_write(
            memory_type='episodic',
            source=_infer_source(),
            text=entry,
            location=f'file:{path}',
            payload={'mood_desc': mood_desc, 'tags': tags or []},
        )

    async def append_visitor(self, source_key: str, name: str,
                             entry: str) -> None:
        """Append an entry to a visitor's memory file.

        File: visitors/{source_key}.md
        """
        if not source_key or not entry:
            return
        now = clock.now()
        date_str = now.strftime('%Y-%m-%d %H:%M')

        # Create file with header if new
        path = self._path('visitors', f'{source_key}.md')
        if not os.path.exists(path):
            header = f'# Visitor: {name or source_key}\n\n'
            self._safe_write(path, header, mode='w')

        block = f'\n## {date_str}\n\n{entry.strip()}\n\n---\n'
        self._safe_write(path, block)
        await self._log_write(
            memory_type='semantic',
            source=_infer_source(),
            text=block,
            location=f'file:{path}',
            payload={'visitor': source_key, 'name': name},
        )

    async def append_reflection(self, date: str, phase: str,
                                text: str) -> None:
        """Write a sleep/nap reflection.

        File: reflections/{date}-{phase}.md
        """
        if not text:
            return
        now = clock.now()
        time_str = now.strftime('%H:%M')

        entry = f'\n## {time_str}\n\n{text.strip()}\n'
        path = self._path('reflections', f'{date}-{phase}.md')
        self._safe_write(path, entry)
        await self._log_write(
            memory_type='summary',
            source='sleep',
            text=entry,
            location=f'file:{path}',
            payload={'phase': phase, 'date': date},
            sleep_session_id=f"sleep-{date}-{phase}",
        )

    async def append_browse(self, date: str, slug: str, text: str) -> None:
        """Write web search results.

        File: browse/{date}-{slug}.md
        """
        if not text:
            return
        path = self._path('browse', f'{date}-{slug}.md')
        self._safe_write(path, text.strip() + '\n')
        await self._log_write(
            memory_type='episodic',
            source=_infer_source(),
            text=text,
            location=f'file:{path}',
            payload={'slug': slug, 'date': date},
        )

    async def append_thread(self, slug: str, entry: str) -> None:
        """Append to a thought thread.

        File: threads/{slug}.md
        """
        if not slug or not entry:
            return
        now = clock.now()
        date_str = now.strftime('%Y-%m-%d %H:%M')

        block = f'\n## {date_str}\n\n{entry.strip()}\n'
        path = self._path('threads', f'{slug}.md')
        self._safe_write(path, block)
        await self._log_write(
            memory_type='episodic',
            source=_infer_source(),
            text=block,
            location=f'file:{path}',
            payload={'slug': slug},
        )

    async def append_collection(self, entry: str) -> None:
        """Append to the collection catalog.

        File: collection/catalog.md
        """
        if not entry:
            return
        path = self._path('collection', 'catalog.md')

        # Create with header if new
        if not os.path.exists(path):
            self._safe_write(path, '# My Collection\n\n', mode='w')

        self._safe_write(path, entry.strip() + '\n')
        await self._log_write(
            memory_type='semantic',
            source=_infer_source(),
            text=entry,
            location=f'file:{path}',
            payload={},
        )

    async def write_self_file(self, filename: str, content: str) -> None:
        """Write/overwrite a self-knowledge file.  Sleep-only operation.

        File: self/{filename}.md (or self/{filename} if already has extension)
        """
        if not filename or not content:
            return
        if not filename.endswith('.md'):
            filename = f'{filename}.md'
        path = self._path('self', filename)
        self._safe_write(path, content, mode='w')
        await self._log_write(
            memory_type='summary',
            source='sleep',
            text=content,
            location=f'file:{path}',
            payload={'filename': filename},
            sleep_session_id=f"sleep-{clock.now().date().isoformat()}",
        )

    async def annotate(self, filepath: str, note: str) -> None:
        """Add a bracketed annotation to an existing file.  Sleep-only.

        Format: [annotation — {date}] {note}
        """
        if not filepath or not note:
            return
        full_path = self._path(filepath)
        if not os.path.exists(full_path):
            return
        date_str = clock.now().strftime('%Y-%m-%d')
        annotation = f'\n[annotation \u2014 {date_str}] {note.strip()}\n'
        self._safe_write(full_path, annotation)
        await self._log_write(
            memory_type='summary',
            source='sleep',
            text=annotation,
            location=f'file:{full_path}',
            payload={'filepath': filepath},
            sleep_session_id=f"sleep-{clock.now().date().isoformat()}",
        )


def slugify(text: str, max_len: int = 50) -> str:
    """Convert text to a filename-safe slug."""
    slug = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
    return slug[:max_len]


# ── Module singleton ──

_instance: MemoryWriter | None = None


def get_memory_writer() -> MemoryWriter:
    """Get or create the global MemoryWriter instance."""
    global _instance
    if _instance is None:
        _instance = MemoryWriter()
        _instance.ensure_dirs()
    return _instance


def reset_memory_writer() -> None:
    """Reset the singleton (for tests)."""
    global _instance
    _instance = None
