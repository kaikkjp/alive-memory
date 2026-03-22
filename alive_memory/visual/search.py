"""Visual embedding search against external SQLite databases."""

from __future__ import annotations

import logging
import math
import sqlite3
import struct
from pathlib import Path

from alive_memory.visual import VisualMatch, VisualSource

log = logging.getLogger(__name__)


async def search_visual(
    source: VisualSource,
    query: str,
    *,
    limit: int = 5,
    boundary: int | None = None,
) -> list[VisualMatch]:
    """Search a visual embedding database for pages matching *query*.

    Embeds the query text using the source's embedder, then performs a
    brute-force cosine similarity scan over the stored embeddings.

    Args:
        source: Visual source descriptor (DB path, embedder, schema).
        query: Natural-language query to embed and search for.
        limit: Maximum number of results to return.
        boundary: If the source has ``max_boundary_col`` set, only rows
            where that column <= *boundary* are considered.  Ignored if
            ``max_boundary_col`` is ``None``.

    Returns:
        Top matches sorted by descending cosine similarity.
    """
    # 1. Embed the query text
    query_vec = await source.embedder.embed(query)

    # 2. Build SQL query
    db_path = Path(source.path)
    if not db_path.exists():
        raise FileNotFoundError(f"Visual DB not found: {db_path}")

    select_cols = [source.content_col, source.embedding_col, *source.metadata_cols]
    col_list = ", ".join(select_cols)
    sql = f"SELECT {col_list} FROM {source.table}"  # noqa: S608

    params: list = []
    if source.max_boundary_col and boundary is not None:
        sql += f" WHERE CAST({source.max_boundary_col} AS INTEGER) <= ?"
        params.append(boundary)

    # 3. Read rows from the external DB (read-only)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    log.debug("Visual search: %d candidate rows from %s", len(rows), db_path.name)

    # 4. Score each row by cosine similarity
    scored: list[tuple[float, str, dict]] = []
    meta_start = 2  # after content_col and embedding_col
    dim = source.embedder.dimensions

    for row in rows:
        filepath = row[0]
        blob = row[1]
        metadata = {
            col: row[meta_start + i] for i, col in enumerate(source.metadata_cols)
        }

        # Decode float32 BLOB
        if blob is None or len(blob) != dim * 4:
            continue
        stored_vec = struct.unpack(f"<{dim}f", blob)

        score = _cosine_similarity(query_vec, stored_vec)
        scored.append((score, filepath, metadata))

    # 5. Sort descending by score and return top results
    scored.sort(key=lambda x: x[0], reverse=True)

    results = [
        VisualMatch(filepath=filepath, score=score, metadata=metadata)
        for score, filepath, metadata in scored[:limit]
    ]

    if results:
        log.debug(
            "Visual search top result: %s (score=%.4f)",
            results[0].filepath,
            results[0].score,
        )

    return results


def _cosine_similarity(
    a: list[float] | tuple[float, ...],
    b: list[float] | tuple[float, ...],
) -> float:
    """Compute cosine similarity between two vectors."""
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    denom = math.sqrt(norm_a) * math.sqrt(norm_b)
    if denom == 0.0:
        return 0.0
    return dot / denom
