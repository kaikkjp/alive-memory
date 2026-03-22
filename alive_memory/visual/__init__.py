"""Visual memory — search external image/media embedding databases."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from alive_memory.embeddings.base import EmbeddingProvider


@dataclass
class VisualSource:
    """Descriptor for an external visual embedding database.

    Points to a SQLite DB containing pre-computed embeddings (e.g. manga
    pages embedded with Gemini multimodal).  alive-memory reads this DB
    at recall/dream time — it never writes to it.

    Args:
        path: Path to the SQLite database file.
        embedder: Embedding provider whose vector space matches the
            stored embeddings.  Query text is embedded with this before
            cosine comparison.
        table: Table name containing the embeddings.
        embedding_col: Column holding the raw embedding BLOB (float32).
        content_col: Column holding the content reference (e.g. filepath).
        metadata_cols: Additional columns to include in search results.
        max_boundary_col: If set, search is filtered to rows where this
            column's value is <= the caller-supplied boundary.  Used for
            sequential reading progress (e.g. ``chapter_num``).
    """

    path: str | Path
    embedder: EmbeddingProvider
    table: str = "pages"
    embedding_col: str = "embedding"
    content_col: str = "filepath"
    metadata_cols: list[str] = field(
        default_factory=lambda: ["chapter_num", "page_num"]
    )
    max_boundary_col: str | None = None


@dataclass
class VisualMatch:
    """A single result from a visual embedding search.

    Attributes:
        filepath: Content reference from the DB (e.g. image path).
        score: Cosine similarity between query and stored embedding.
        metadata: Extra column values (chapter_num, page_num, etc.).
    """

    filepath: str
    score: float
    metadata: dict


__all__ = ["VisualMatch", "VisualSource"]
