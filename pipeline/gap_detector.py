"""Gap Detector — information gap scoring on the Goldilocks curve. No LLM.

TASK-042: Compares text fragments (notification titles, visitor speech, journal
entries) against memory embeddings to score information gaps.

Foreign (<0.15 relevance) = ignored (too alien to engage with).
Partial (0.15–0.85) = curiosity spike (information gap detected).
Known (>0.85) = ignored (nothing new to learn).
Peak curiosity at 0.5 relevance (maximum gap intensity).

Uses embedding cosine similarity for relevance scoring. The embedding index
is preloaded at startup and refreshed periodically for performance.
"""

import math
import struct
from dataclasses import dataclass, field
from typing import Optional

from models.pipeline import TextFragment, GapScore

# ── Goldilocks curve parameters ──
FOREIGN_THRESHOLD = 0.15   # below this: too alien, no curiosity
KNOWN_THRESHOLD = 0.85     # above this: already known, no curiosity
PEAK_RELEVANCE = 0.5       # maximum gap intensity
MAX_CURIOSITY_DELTA = 0.15 # max drive change per item

# Matching memory display cap
MAX_MATCHING_DISPLAY = 3


@dataclass
class EmbeddingEntry:
    """A single entry in the embedding index."""
    source_type: str    # 'conversation', 'monologue', 'totem', 'thread'
    source_id: str
    text_snippet: str   # first ~100 chars for display
    embedding: list[float] = field(default_factory=list)


@dataclass
class EmbeddingIndex:
    """Preloaded embedding index for fast gap detection.

    Stores all memory/totem/thread embeddings in a flat list.
    Cosine similarity is computed per-entry (pure Python — no numpy dependency).
    For typical index sizes (<1000 entries), this completes in <50ms.
    """
    entries: list[EmbeddingEntry] = field(default_factory=list)
    dimension: int = 1536  # text-embedding-3-small

    @property
    def size(self) -> int:
        return len(self.entries)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors. Pure Python.

    Returns 0.0 on degenerate inputs (zero vectors, mismatched dimensions).
    """
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot / (norm_a * norm_b)


def _goldilocks_curve(relevance: float) -> float:
    """Goldilocks curve: peak curiosity at relevance=0.5.

    gap_intensity = 1.0 - abs(relevance - 0.5) * 2
    This gives a triangle peaking at 1.0 when relevance=0.5,
    falling to 0.0 at relevance=0.0 and relevance=1.0.
    """
    return max(0.0, 1.0 - abs(relevance - PEAK_RELEVANCE) * 2)


def _classify_gap(relevance: float) -> str:
    """Classify relevance into gap type."""
    if relevance < FOREIGN_THRESHOLD:
        return 'foreign'
    elif relevance > KNOWN_THRESHOLD:
        return 'known'
    return 'partial'


def detect_gaps(
    fragments: list[TextFragment],
    index: EmbeddingIndex,
    fragment_embeddings: dict[str, list[float]],
) -> list[GapScore]:
    """Score text fragments against the embedding index.

    Args:
        fragments: Text fragments to score.
        index: Preloaded embedding index (memories, totems, threads).
        fragment_embeddings: Map of fragment.source_id -> embedding vector.
            Fragments without embeddings are scored as foreign.

    Returns:
        List of GapScore results, one per fragment.
    """
    results = []

    for fragment in fragments:
        embedding = fragment_embeddings.get(fragment.source_id)
        if not embedding or not index.entries:
            # No embedding available or empty index — treat as foreign
            results.append(GapScore(
                fragment=fragment,
                relevance=0.0,
                gap_type='foreign',
                curiosity_delta=0.0,
            ))
            continue

        # Compute similarity against all index entries
        best_similarity = 0.0
        matching_memories = []
        matching_threads = []

        for entry in index.entries:
            if not entry.embedding:
                continue
            sim = _cosine_similarity(embedding, entry.embedding)
            if sim > best_similarity:
                best_similarity = sim

            # Track matching entries (above foreign threshold)
            if sim >= FOREIGN_THRESHOLD:
                label = f"{entry.source_type}: {entry.text_snippet[:60]}"
                if entry.source_type == 'thread':
                    if len(matching_threads) < MAX_MATCHING_DISPLAY:
                        matching_threads.append(label)
                else:
                    if len(matching_memories) < MAX_MATCHING_DISPLAY:
                        matching_memories.append(label)

        # Clamp similarity to [0, 1]
        relevance = max(0.0, min(1.0, best_similarity))

        # Classify and compute curiosity delta
        gap_type = _classify_gap(relevance)
        if gap_type == 'partial':
            gap_intensity = _goldilocks_curve(relevance)
            curiosity_delta = gap_intensity * MAX_CURIOSITY_DELTA
        else:
            curiosity_delta = 0.0

        # Suggest curiosity type
        suggested_type = None
        if gap_type == 'partial':
            if matching_threads:
                suggested_type = 'epistemic'  # connects to active question/thread
            else:
                suggested_type = 'diversive'  # new territory to explore

        results.append(GapScore(
            fragment=fragment,
            relevance=relevance,
            gap_type=gap_type,
            matching_memories=matching_memories,
            matching_threads=matching_threads,
            curiosity_delta=curiosity_delta,
            suggested_curiosity_type=suggested_type,
        ))

    return results


def deserialize_embedding(blob: bytes, dimension: int = 1536) -> list[float]:
    """Deserialize a float32 blob into a list of floats.

    Compatible with sqlite_vec.serialize_float32() format.
    """
    if not blob:
        return []
    count = len(blob) // 4
    if count != dimension:
        return []
    return list(struct.unpack(f'{count}f', blob))


async def load_embedding_index(db_module) -> EmbeddingIndex:
    """Load all memory embeddings into an in-memory index.

    Loads from cold_memory_vec (conversations, monologues) and supplements
    with totem descriptions and active thread titles.

    Args:
        db_module: The db module (for testability — avoids direct import).

    Returns:
        EmbeddingIndex ready for gap detection.
    """
    index = EmbeddingIndex()

    # Load cold memory embeddings
    try:
        conn = await db_module.get_db()
        cursor = await conn.execute(
            """SELECT source_type, source_id, text_content, embedding
               FROM cold_memory_vec
               LIMIT 1000"""
        )
        rows = await cursor.fetchall()
        for row in rows:
            emb = deserialize_embedding(row['embedding'])
            if emb:
                index.entries.append(EmbeddingEntry(
                    source_type=row['source_type'],
                    source_id=row['source_id'],
                    text_snippet=row['text_content'][:100] if row['text_content'] else '',
                    embedding=emb,
                ))
    except Exception as e:
        print(f"  [GapDetector] Failed to load cold memory embeddings: {e}")

    print(f"  [GapDetector] Loaded {index.size} embeddings into index")
    return index


def format_gap_annotation(gap_score: GapScore) -> str:
    """Format a gap score as a diegetic annotation for cortex.

    Returns empty string for foreign/known content (no annotation needed).
    """
    if gap_score.gap_type != 'partial':
        return ''

    parts = []
    if gap_score.matching_threads:
        thread_topics = [t.split(': ', 1)[-1] if ': ' in t else t
                        for t in gap_score.matching_threads[:2]]
        parts.append(f"this connects to something you're thinking about: {', '.join(thread_topics)}")
    elif gap_score.matching_memories:
        mem_topics = [m.split(': ', 1)[-1] if ': ' in m else m
                     for m in gap_score.matching_memories[:2]]
        parts.append(f"this connects to something you know about: {', '.join(mem_topics)}")
    else:
        if gap_score.relevance > 0.4:
            parts.append("you've heard of this but don't know the details")
        else:
            parts.append("this is new to you but not completely foreign")

    return ' — '.join(parts)
