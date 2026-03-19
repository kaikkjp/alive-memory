"""Wake phase — post-sleep transition orchestrator.

The SDK owns memory concerns (cold embedding, day memory flush, stale moment
cleanup).  Application-specific concerns (thread lifecycle, content pool,
drive reset, self-file updates) are delegated to caller-provided hooks via
the ``WakeHooks`` protocol.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from alive_memory.embeddings.base import EmbeddingProvider
from alive_memory.storage.base import BaseStorage
from alive_memory.types import ColdEntryType, WakeReport

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class WakeConfig:
    """Tuneable knobs for the wake transition."""
    thread_dormant_hours: int = 48
    thread_archive_days: int = 7
    pool_max_unseen: int = 50
    stale_moment_hours: int = 72
    morning_defaults: dict[str, float] = field(default_factory=dict)
    preserve_fields: list[str] = field(default_factory=lambda: ["mood_valence"])


# ---------------------------------------------------------------------------
# Hook protocol — apps implement these
# ---------------------------------------------------------------------------

@runtime_checkable
class WakeHooks(Protocol):
    async def manage_threads(self, dormant_hours: int, archive_days: int) -> int: ...
    async def cleanup_pool(self, max_unseen: int) -> int: ...
    async def reset_drives(self, defaults: dict[str, float], preserve: list[str]) -> None: ...
    async def update_self_files(self) -> None: ...


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def run_wake_transition(
    storage: BaseStorage,
    *,
    hooks: WakeHooks | None = None,
    embedder: EmbeddingProvider | None = None,
    config: WakeConfig | None = None,
) -> WakeReport:
    """Run the wake transition after consolidation.

    Orchestration order:
      1. App hooks (if provided): manage_threads → cleanup_pool →
         reset_drives → update_self_files
      2. SDK memory concerns: flush stale moments → embed unembedded cold
         entries → flush processed day memory

    Each hook call is individually guarded — a single hook failure will not
    prevent subsequent hooks or SDK cleanup from running.
    """
    cfg = config or WakeConfig()
    start_ms = int(time.monotonic() * 1000)
    report = WakeReport()

    # ── App hooks ─────────────────────────────────────────────────
    if hooks is not None:
        # manage_threads
        try:
            report.threads_managed = await hooks.manage_threads(
                cfg.thread_dormant_hours, cfg.thread_archive_days,
            )
        except Exception:
            logger.warning("Wake hook manage_threads failed", exc_info=True)

        # cleanup_pool
        try:
            report.pool_items_cleaned = await hooks.cleanup_pool(
                cfg.pool_max_unseen,
            )
        except Exception:
            logger.warning("Wake hook cleanup_pool failed", exc_info=True)

        # reset_drives
        try:
            await hooks.reset_drives(
                cfg.morning_defaults, cfg.preserve_fields,
            )
        except Exception:
            logger.warning("Wake hook reset_drives failed", exc_info=True)

        # update_self_files
        try:
            await hooks.update_self_files()
        except Exception:
            logger.warning("Wake hook update_self_files failed", exc_info=True)

    # ── SDK memory concerns ───────────────────────────────────────

    # Flush stale (old + unprocessed) moments
    try:
        report.stale_moments_flushed = await storage.flush_stale_moments(
            cfg.stale_moment_hours,
        )
    except Exception:
        logger.warning("Wake: flush_stale_moments failed", exc_info=True)

    # Embed unembedded cold entries
    if embedder is not None:
        try:
            unprocessed = await storage.get_unprocessed_moments()
            embedded = 0
            for moment in unprocessed:
                try:
                    embedding = await embedder.embed(moment.content)
                    await storage.store_cold_memory(
                        content=moment.content,
                        embedding=embedding,
                        entry_type=ColdEntryType.EVENT,
                        raw_content=moment.content,
                        source_moment_id=moment.id,
                        metadata={
                            "event_type": moment.event_type.value,
                            "valence": moment.valence,
                            "salience": moment.salience,
                        },
                        session_id=moment.metadata.get("session_id"),
                    )
                    # Prevent duplicate wake embeddings on subsequent runs.
                    await storage.mark_moment_processed(moment.id)
                    embedded += 1
                except Exception:
                    logger.warning(
                        "Wake: failed to embed moment %s", moment.id, exc_info=True,
                    )
            report.cold_embeddings_added = embedded
        except Exception:
            logger.warning("Wake: cold embedding step failed", exc_info=True)

    # Flush processed day memory
    try:
        report.day_memory_flushed = await storage.flush_day_memory()
    except Exception:
        logger.warning("Wake: flush_day_memory failed", exc_info=True)

    report.duration_ms = int(time.monotonic() * 1000) - start_ms
    return report
