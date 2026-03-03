"""Merging — combine similar memories.

When two memories have very high cosine similarity, they are
merged into a single stronger memory. This prevents redundancy
and strengthens repeated experiences.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from alive_memory.config import AliveConfig
from alive_memory.storage.base import BaseStorage
from alive_memory.types import Memory


async def merge_similar(
    memories: list[Memory],
    storage: BaseStorage,
    *,
    config: AliveConfig | None = None,
) -> int:
    """Find and merge highly similar memory pairs.

    Returns the number of merges performed.
    """
    cfg = config or AliveConfig()
    threshold = cfg.get("consolidation.merge_similarity", 0.85)
    count = 0

    with_embeddings = [m for m in memories if m.embedding is not None]
    merged_ids: set[str] = set()

    for i, a in enumerate(with_embeddings):
        if a.id in merged_ids:
            continue
        for b in with_embeddings[i + 1:]:
            if b.id in merged_ids:
                continue
            if a.memory_type != b.memory_type:
                continue

            sim = _cosine_similarity(a.embedding, b.embedding)
            if sim >= threshold:
                merged = _merge_pair(a, b)
                await storage.merge_memories([a.id, b.id], merged)
                merged_ids.add(a.id)
                merged_ids.add(b.id)
                count += 1
                break

    return count


def _merge_pair(a: Memory, b: Memory) -> Memory:
    """Merge two memories into one."""
    content = a.content if len(a.content) >= len(b.content) else b.content

    coupling = dict(a.drive_coupling)
    for k, v in b.drive_coupling.items():
        coupling[k] = max(coupling.get(k, 0), v)

    meta = dict(a.metadata)
    meta.update(b.metadata)
    meta["merged_from"] = [a.id, b.id]

    return Memory(
        id=str(uuid.uuid4()),
        content=content,
        memory_type=a.memory_type,
        strength=min(1.0, max(a.strength, b.strength) * 1.1),
        valence=(a.valence + b.valence) / 2,
        formed_at=max(a.formed_at, b.formed_at),
        last_recalled=max(
            a.last_recalled or a.formed_at,
            b.last_recalled or b.formed_at,
        ),
        recall_count=a.recall_count + b.recall_count,
        source_event=a.source_event,
        drive_coupling=coupling,
        embedding=a.embedding,
        metadata=meta,
    )


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
