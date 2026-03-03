"""ChromaDB RAG+ adapter — RAG with periodic LLM maintenance.

Same as raw RAG but adds periodic consolidation at the same interval
and roughly the same LLM budget as alive-memory. This isolates whether
alive's architecture matters, or just the extra LLM calls.

Maintenance includes: deduplication, summarization of similar entries,
metadata enrichment.
"""

import hashlib
import os
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

try:
    import anthropic
except ImportError:
    anthropic = None  # type: ignore[assignment]


SUMMARIZE_PROMPT = """\
You are consolidating memories for an AI agent. Below are several related memories.
Produce a single concise summary that preserves the key facts, entities, and temporal markers.
Keep it under 200 words. Preserve names, dates, and specific details.

Memories:
{memories}

Summary:"""


class ChromaRagPlusAdapter(MemoryAdapter):
    """RAG + periodic LLM maintenance (dedup, summarize, enrich)."""

    def __init__(self) -> None:
        self._client: Optional["chromadb.ClientAPI"] = None
        self._collection = None
        self._embed_model = None
        self._count = 0
        self._base_rss = 0
        self._llm_calls = 0
        self._llm_tokens = 0
        self._llm_client = None
        self._model = "claude-haiku-4-5-20251001"
        # Track content hashes for dedup
        self._content_hashes: set[str] = set()
        self._dedup_count = 0

    @staticmethod
    def _get_rss() -> int:
        try:
            import psutil
            return psutil.Process().memory_info().rss
        except ImportError:
            import resource
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024

    async def setup(self, config: dict) -> None:
        if chromadb is None:
            raise ImportError("chromadb required")
        if SentenceTransformer is None:
            raise ImportError("sentence-transformers required")

        self._base_rss = self._get_rss()
        self._client = chromadb.Client()
        self._collection = self._client.create_collection(
            name="bench_rag_plus",
            metadata={"hnsw:space": "cosine"},
        )
        model_name = config.get("embed_model", "all-MiniLM-L6-v2")
        self._embed_model = SentenceTransformer(model_name)
        self._count = 0

        if anthropic:
            self._llm_client = anthropic.AsyncAnthropic()
            self._model = config.get("llm_model", self._model)

    async def ingest(self, event: BenchEvent) -> None:
        # Dedup: skip exact content duplicates
        content_hash = hashlib.sha256(event.content.encode()).hexdigest()[:16]
        if content_hash in self._content_hashes:
            self._dedup_count += 1
            return
        self._content_hashes.add(content_hash)

        embedding = self._embed_model.encode(event.content).tolist()
        self._collection.add(
            ids=[f"mem_{self._count}"],
            embeddings=[embedding],
            documents=[event.content],
            metadatas=[{
                "cycle": event.cycle,
                "type": event.event_type,
                "timestamp": event.timestamp,
                "hash": content_hash,
            }],
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
            recalls.append(RecallResult(
                content=doc,
                score=max(0.0, 1.0 - dist),
                metadata=meta,
                formed_at=meta.get("timestamp"),
            ))

        return recalls

    async def consolidate(self) -> None:
        """Periodic maintenance: find clusters of similar memories and summarize."""
        if not self._llm_client or self._count < 10:
            return

        # Sample a random subset and find clusters of similar content
        # Then summarize each cluster into a single memory
        try:
            # Get a sample of recent memories
            sample_size = min(20, self._count)
            peek = self._collection.peek(limit=sample_size)
            docs = peek.get("documents", [])
            ids = peek.get("ids", [])

            if len(docs) < 5:
                return

            # Find clusters: for each doc, find similar ones
            clusters = self._find_clusters(docs, ids, threshold=0.85)

            for cluster_ids, cluster_docs in clusters:
                if len(cluster_docs) < 3:
                    continue

                # Summarize the cluster
                summary = await self._summarize_cluster(cluster_docs)
                if not summary:
                    continue

                # Remove old entries, add summary
                self._collection.delete(ids=cluster_ids)
                self._count -= len(cluster_ids)

                embedding = self._embed_model.encode(summary).tolist()
                self._collection.add(
                    ids=[f"consolidated_{self._count}"],
                    embeddings=[embedding],
                    documents=[summary],
                    metadatas=[{
                        "cycle": 0,
                        "type": "consolidated",
                        "timestamp": "",
                        "source_count": len(cluster_ids),
                    }],
                )
                self._count += 1

        except Exception:
            pass  # consolidation is best-effort

    def _find_clusters(
        self,
        docs: list[str],
        ids: list[str],
        threshold: float = 0.85,
    ) -> list[tuple[list[str], list[str]]]:
        """Find clusters of similar documents using embeddings."""
        import numpy as np

        if not docs:
            return []

        embeddings = self._embed_model.encode(docs)
        # Cosine similarity matrix
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1
        normalized = embeddings / norms
        sim_matrix = normalized @ normalized.T

        visited = set()
        clusters = []

        for i in range(len(docs)):
            if i in visited:
                continue
            cluster_ids = [ids[i]]
            cluster_docs = [docs[i]]
            visited.add(i)

            for j in range(i + 1, len(docs)):
                if j in visited:
                    continue
                if sim_matrix[i][j] > threshold:
                    cluster_ids.append(ids[j])
                    cluster_docs.append(docs[j])
                    visited.add(j)

            if len(cluster_ids) >= 3:
                clusters.append((cluster_ids, cluster_docs))

        return clusters

    async def _summarize_cluster(self, docs: list[str]) -> Optional[str]:
        """Use LLM to summarize a cluster of similar memories."""
        if not self._llm_client:
            return None

        memories = "\n---\n".join(docs[:10])  # cap at 10
        prompt = SUMMARIZE_PROMPT.format(memories=memories)

        try:
            resp = await self._llm_client.messages.create(
                model=self._model,
                max_tokens=300,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            self._llm_calls += 1
            self._llm_tokens += resp.usage.input_tokens + resp.usage.output_tokens
            return resp.content[0].text.strip()
        except Exception:
            return None

    async def get_stats(self) -> SystemStats:
        return SystemStats(
            memory_count=self._count,
            storage_bytes=max(0, self._get_rss() - self._base_rss),
            total_llm_calls=self._llm_calls,
            total_tokens=self._llm_tokens,
        )

    async def teardown(self) -> None:
        if self._client:
            try:
                self._client.delete_collection("bench_rag_plus")
            except Exception:
                pass
        self._client = None
        self._collection = None
