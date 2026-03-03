"""ChromaDB RAG adapter — the baseline.

Vector store + cosine similarity + top-k retrieval. No LLM calls,
no consolidation, no maintenance. The simplest possible memory system.
"""

import os
import sys
from typing import Optional

from benchmarks.adapters.base import (
    BenchEvent,
    MemoryAdapter,
    RecallResult,
    SystemStats,
)

try:
    import chromadb
    from sentence_transformers import SentenceTransformer
except ImportError:
    chromadb = None  # type: ignore[assignment]
    SentenceTransformer = None  # type: ignore[assignment, misc]


class ChromaRagAdapter(MemoryAdapter):
    """Baseline RAG: embed everything, retrieve by cosine similarity."""

    def __init__(self) -> None:
        self._client: Optional["chromadb.ClientAPI"] = None
        self._collection = None
        self._embed_model = None
        self._count = 0
        self._base_rss = 0

    @staticmethod
    def _get_rss() -> int:
        """Get current process RSS in bytes."""
        try:
            import psutil

            return psutil.Process().memory_info().rss
        except ImportError:
            # Fallback for systems without psutil
            import resource

            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024

    async def setup(self, config: dict) -> None:
        if chromadb is None:
            raise ImportError("chromadb required: pip install chromadb")
        if SentenceTransformer is None:
            raise ImportError(
                "sentence-transformers required: pip install sentence-transformers"
            )

        self._client = chromadb.Client()
        self._collection = self._client.create_collection(
            name="bench_rag",
            metadata={"hnsw:space": "cosine"},
        )
        model_name = config.get("embed_model", "all-MiniLM-L6-v2")
        self._embed_model = SentenceTransformer(model_name)
        self._count = 0
        # Capture baseline RSS *after* model is loaded so we only measure data storage
        self._base_rss = self._get_rss()

    async def ingest(self, event: BenchEvent) -> None:
        embedding = self._embed_model.encode(event.content).tolist()
        self._collection.add(
            ids=[f"mem_{self._count}"],
            embeddings=[embedding],
            documents=[event.content],
            metadatas=[
                {
                    "cycle": event.cycle,
                    "type": event.event_type,
                    "timestamp": event.timestamp,
                }
            ],
        )
        self._count += 1

    async def recall(self, query: str, limit: int = 5) -> list[RecallResult]:
        if self._count == 0:
            return []

        embedding = self._embed_model.encode(query).tolist()
        actual_limit = min(limit, self._count)
        results = self._collection.query(
            query_embeddings=[embedding], n_results=actual_limit
        )

        recalls = []
        docs = results.get("documents", [[]])[0]
        dists = results.get("distances", [[]])[0]
        metas = results.get("metadatas", [[]])[0]

        for doc, dist, meta in zip(docs, dists, metas):
            recalls.append(
                RecallResult(
                    content=doc,
                    score=max(0.0, 1.0 - dist),  # distance → similarity
                    metadata=meta,
                    formed_at=meta.get("timestamp"),
                )
            )

        return recalls

    async def get_stats(self) -> SystemStats:
        return SystemStats(
            memory_count=self._count,
            storage_bytes=max(0, self._get_rss() - self._base_rss),
            total_llm_calls=0,
            total_tokens=0,
        )

    async def teardown(self) -> None:
        if self._client:
            try:
                self._client.delete_collection("bench_rag")
            except Exception:
                pass
        self._client = None
        self._collection = None
