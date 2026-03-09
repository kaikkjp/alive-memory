"""Vanilla RAG baseline.

Dense retrieval over stored conversation chunks using embedding similarity.
No LLM calls for memory management — only for answer generation.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from benchmarks.academic.harness.base import (
    ConversationTurn,
    MemoryQuery,
    MemorySystemAdapter,
    SystemMetrics,
)
from benchmarks.academic.systems.llm_utils import LLMTracker, llm_answer

try:
    import chromadb
    from sentence_transformers import SentenceTransformer
except ImportError:
    chromadb = None  # type: ignore[assignment]
    SentenceTransformer = None  # type: ignore[assignment, misc]


class RAGMemorySystem(MemorySystemAdapter):
    """Baseline: vector retrieval over conversation chunks."""

    def __init__(self, chunk_size: int = 3, retrieval_k: int = 5) -> None:
        self._client: Optional["chromadb.ClientAPI"] = None
        self._collection = None
        self._embed_model = None
        self._count = 0
        self._chunk_size = chunk_size  # turns per chunk
        self._retrieval_k = retrieval_k
        self._tracker = LLMTracker()
        self._base_rss = 0

    @staticmethod
    def _get_rss() -> int:
        try:
            import psutil
            return psutil.Process().memory_info().rss
        except ImportError:
            import resource
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024

    @property
    def system_id(self) -> str:
        return "rag"

    async def setup(self, config: dict) -> None:
        if chromadb is None:
            raise ImportError("chromadb required: pip install chromadb")
        if SentenceTransformer is None:
            raise ImportError("sentence-transformers required")

        self._base_rss = self._get_rss()
        self._client = chromadb.Client()
        self._collection = self._client.create_collection(
            name="academic_bench_rag",
            metadata={"hnsw:space": "cosine"},
        )
        model_name = config.get("embed_model", "all-MiniLM-L6-v2")
        self._embed_model = SentenceTransformer(model_name)
        self._count = 0
        self._tracker = LLMTracker()
        self._chunk_size = config.get("chunk_size", 3)
        self._retrieval_k = config.get("retrieval_k", 5)

    async def add_conversation(self, turns: list[ConversationTurn]) -> None:
        # Chunk turns into groups
        for i in range(0, len(turns), self._chunk_size):
            chunk_turns = turns[i:i + self._chunk_size]
            chunk_text = "\n".join(
                f"[{t.role}]: {t.content}" for t in chunk_turns
            )

            content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()[:16]
            embedding = self._embed_model.encode(chunk_text).tolist()

            self._collection.add(
                ids=[f"chunk_{self._count}"],
                embeddings=[embedding],
                documents=[chunk_text],
                metadatas=[{
                    "session_id": chunk_turns[0].session_id,
                    "turn_start": chunk_turns[0].turn_id,
                    "turn_end": chunk_turns[-1].turn_id,
                    "hash": content_hash,
                }],
            )
            self._count += 1

    async def answer_query(self, query: MemoryQuery, llm_config: dict) -> str:
        if self._count == 0:
            return await llm_answer(
                question=query.question,
                context="",
                llm_config=llm_config,
                tracker=self._tracker,
            )

        # Retrieve top-k chunks
        embedding = self._embed_model.encode(query.question).tolist()
        k = min(self._retrieval_k, self._count)
        results = self._collection.query(
            query_embeddings=[embedding], n_results=k
        )

        docs = results.get("documents", [[]])[0]
        context = "\n---\n".join(docs)

        return await llm_answer(
            question=query.question,
            context=context,
            llm_config=llm_config,
            tracker=self._tracker,
        )

    async def get_metrics(self) -> SystemMetrics:
        return SystemMetrics(
            total_llm_calls=self._tracker.total_calls,
            total_tokens=self._tracker.total_tokens,
            storage_bytes=max(0, self._get_rss() - self._base_rss),
            memory_count=self._count,
        )

    async def reset(self) -> None:
        if self._client:
            try:
                self._client.delete_collection("academic_bench_rag")
                self._collection = self._client.create_collection(
                    name="academic_bench_rag",
                    metadata={"hnsw:space": "cosine"},
                )
            except Exception:
                pass
        self._count = 0
        self._tracker = LLMTracker()

    async def teardown(self) -> None:
        if self._client:
            try:
                self._client.delete_collection("academic_bench_rag")
            except Exception:
                pass
        self._client = None
        self._collection = None
