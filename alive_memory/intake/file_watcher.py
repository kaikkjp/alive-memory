"""File watcher for automatic media/text ingestion.

Monitors a directory for new files and ingests them via AliveMemory.
Uses polling (no external dependencies) for simplicity.

Usage:
    from alive_memory import AliveMemory
    from alive_memory.intake.file_watcher import FileWatcher

    memory = AliveMemory(...)
    watcher = FileWatcher(memory, watch_dir="./inbox")
    await watcher.start()   # runs in background
    await watcher.stop()    # graceful shutdown
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import mimetypes
from pathlib import Path

from alive_memory import AliveMemory

logger = logging.getLogger(__name__)

# Text file extensions we can read directly
_TEXT_EXTENSIONS = frozenset({
    ".txt", ".md", ".markdown", ".csv", ".json", ".xml",
    ".yaml", ".yml", ".log", ".rst", ".html", ".htm",
})

# Max text file size to read (1 MB)
_MAX_TEXT_BYTES = 1 * 1024 * 1024


class FileWatcher:
    """Watch a directory for new files and ingest them into alive-memory.

    Text files are read directly and passed to intake().
    Media files (images, audio, video, PDFs) are passed to intake_media()
    if a multimodal LLM is available.

    Args:
        memory: AliveMemory instance (must be initialized).
        watch_dir: Directory to watch for new files.
        poll_interval: Seconds between directory scans.
        media_llm: Optional multimodal LLM for media files.
                   Falls back to memory's LLM if it has perceive_media().
        delete_after_ingest: Whether to delete files after successful ingestion.
    """

    def __init__(
        self,
        memory: AliveMemory,
        watch_dir: str | Path = "./inbox",
        *,
        poll_interval: float = 5.0,
        media_llm: object | None = None,
        delete_after_ingest: bool = False,
    ):
        self._memory = memory
        self._watch_dir = Path(watch_dir)
        self._poll_interval = poll_interval
        self._media_llm = media_llm
        self._delete_after = delete_after_ingest
        self._seen: set[Path] = set()
        self._task: asyncio.Task | None = None
        self._running = False

    @property
    def watch_dir(self) -> Path:
        return self._watch_dir

    @property
    def running(self) -> bool:
        return self._running

    @property
    def seen_count(self) -> int:
        return len(self._seen)

    async def start(self) -> None:
        """Start watching in the background."""
        if self._running:
            return

        self._watch_dir.mkdir(parents=True, exist_ok=True)

        # Mark existing files as seen (don't re-ingest on startup)
        self._seen = set(self._watch_dir.iterdir())

        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("FileWatcher started: %s", self._watch_dir)

    async def stop(self) -> None:
        """Stop watching."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        logger.info("FileWatcher stopped")

    async def ingest_file(self, path: Path) -> bool:
        """Ingest a single file. Returns True if successfully processed."""
        if not path.is_file():
            return False

        try:
            if _is_text_file(path):
                return await self._ingest_text(path)
            elif _is_media_file(path):
                return await self._ingest_media(path)
            else:
                logger.debug("Skipping unsupported file: %s", path.name)
                return False
        except Exception:
            logger.exception("Failed to ingest %s", path.name)
            return False

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                await self._scan_once()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in file watcher scan")
            await asyncio.sleep(self._poll_interval)

    async def _scan_once(self) -> None:
        """Scan for new files and ingest them."""
        if not self._watch_dir.is_dir():
            return

        current_files = set(self._watch_dir.iterdir())
        new_files = current_files - self._seen

        for path in sorted(new_files):
            if path.name.startswith("."):
                self._seen.add(path)
                continue

            logger.info("New file detected: %s", path.name)
            success = await self.ingest_file(path)

            if success:
                self._seen.add(path)
                if self._delete_after:
                    try:
                        path.unlink()
                        logger.info("Deleted after ingest: %s", path.name)
                    except OSError:
                        logger.warning("Could not delete: %s", path.name)
            # Failed files are NOT added to _seen, so they retry on next scan

    async def _ingest_text(self, path: Path) -> bool:
        """Read and ingest a text file."""
        size = path.stat().st_size
        if size > _MAX_TEXT_BYTES:
            logger.warning("Text file too large (%d bytes), truncating: %s", size, path.name)

        content = path.read_text(encoding="utf-8", errors="replace")[:_MAX_TEXT_BYTES]
        if not content.strip():
            return False

        moment = await self._memory.intake(
            event_type="observation",
            content=content,
            metadata={"source": "file_watcher", "filename": path.name},
        )
        logger.info(
            "Ingested text %s → %s",
            path.name,
            f"moment {moment.id}" if moment else "below threshold",
        )
        return True

    async def _ingest_media(self, path: Path) -> bool:
        """Ingest a media file via multimodal LLM."""
        provider = self._media_llm
        if provider is None and hasattr(self._memory, "_llm"):
            llm = self._memory._llm
            if llm is not None and hasattr(llm, "perceive_media"):
                provider = llm

        if provider is None or not hasattr(provider, "perceive_media"):
            logger.warning(
                "Skipping media file %s — no multimodal LLM available", path.name
            )
            return False

        moment = await self._memory.intake_media(
            path,
            media_llm=provider,
            metadata={"source": "file_watcher", "filename": path.name},
        )
        logger.info(
            "Ingested media %s → %s",
            path.name,
            f"moment {moment.id}" if moment else "below threshold",
        )
        return True


def _is_text_file(path: Path) -> bool:
    """Check if a file is a readable text file."""
    return path.suffix.lower() in _TEXT_EXTENSIONS


def _is_media_file(path: Path) -> bool:
    """Check if a file is a supported media file."""
    mime, _ = mimetypes.guess_type(str(path))
    if mime is None:
        return False
    return (
        mime.startswith("image/")
        or mime.startswith("audio/")
        or mime.startswith("video/")
        or mime == "application/pdf"
    )
