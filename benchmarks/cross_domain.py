"""Cross-domain transfer runner — tests memory transfer across scenarios.

Phase 1: Ingest events from scenario A (training domain)
Phase 2: Run queries from scenario B (test domain) against populated memory
Measures how well memories from one domain help answer queries in another.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from benchmarks.adapters.base import BenchEvent, MemoryAdapter
from benchmarks.runner import load_ground_truth, load_jsonl
from benchmarks.scoring.hard_truth import (
    aggregate_by_category,
    aggregate_scores,
    score_negative_recall,
    score_recall,
)


@dataclass
class CrossDomainResult:
    """Result from cross-domain transfer test."""

    system_id: str
    train_stream: str
    test_stream: str
    transfer_f1: float  # F1 on test queries after training on different domain
    baseline_f1: float  # F1 on test queries after training on same domain (if available)
    transfer_ratio: float  # transfer_f1 / baseline_f1 (if baseline available)
    interference_rate: float  # fraction of results contaminated by training domain
    recall_by_category: dict = field(default_factory=dict)
    total_train_events: int = 0
    total_test_queries: int = 0
    wall_time_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "system_id": self.system_id,
            "train_stream": self.train_stream,
            "test_stream": self.test_stream,
            "transfer_f1": self.transfer_f1,
            "baseline_f1": self.baseline_f1,
            "transfer_ratio": self.transfer_ratio,
            "interference_rate": self.interference_rate,
            "recall_by_category": self.recall_by_category,
            "total_train_events": self.total_train_events,
            "total_test_queries": self.total_test_queries,
            "wall_time_seconds": self.wall_time_seconds,
        }

    def save(self, path: str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2))


class CrossDomainRunner:
    """Runs cross-domain transfer tests."""

    def __init__(
        self,
        train_stream_path: str,
        test_query_path: str,
        test_gt_path: str,
        max_cycles: int | None = None,
        consolidation_interval: int = 500,
    ):
        self.train_events = load_jsonl(train_stream_path)
        self.test_queries = load_jsonl(test_query_path)
        self.test_ground_truth = load_ground_truth(test_gt_path)
        self.consolidation_interval = consolidation_interval

        if max_cycles:
            self.train_events = [
                e for e in self.train_events if e["cycle"] <= max_cycles
            ]

    async def run(
        self,
        adapter: MemoryAdapter,
        system_id: str,
        train_stream: str = "",
        test_stream: str = "",
    ) -> CrossDomainResult:
        """Run cross-domain transfer test."""
        await adapter.setup({})
        wall_start = time.monotonic()

        # Phase 1: Ingest training domain events (no queries)
        for i, event_dict in enumerate(self.train_events):
            event = BenchEvent.from_dict(event_dict)
            await adapter.ingest(event)

            cycle = event_dict["cycle"]
            if cycle > 0 and cycle % self.consolidation_interval == 0:
                await adapter.consolidate()

            if (i + 1) % 1000 == 0:
                print(f"  [{system_id}] Ingested {i + 1}/{len(self.train_events)} train events")

        # Phase 2: Run test domain queries
        all_scores = []
        for q in self.test_queries:
            query_id = q["query_id"]
            category = q["category"]
            gt = self.test_ground_truth.get(query_id, {})

            results = await adapter.recall(q["query"], limit=5)

            if category == "negative_recall":
                forbidden = gt.get("forbidden_memories", [])
                scored = score_negative_recall(query_id, results, forbidden)
            else:
                expected = gt.get("expected_memories", [])
                scored = score_recall(query_id, category, results, expected)

            all_scores.append(scored)

        wall_time = time.monotonic() - wall_start
        await adapter.teardown()

        # Compute results
        summary = aggregate_scores(all_scores)
        by_category = aggregate_by_category(all_scores)

        # Interference: fraction of results that contain training domain topics
        # but are irrelevant to test queries
        interference_count = sum(s.noise_count for s in all_scores)
        total_retrieved = sum(s.retrieved_count for s in all_scores)
        interference_rate = interference_count / max(total_retrieved, 1)

        return CrossDomainResult(
            system_id=system_id,
            train_stream=train_stream,
            test_stream=test_stream,
            transfer_f1=summary.get("f1", 0.0),
            baseline_f1=0.0,  # Set externally if same-domain baseline available
            transfer_ratio=0.0,  # Computed externally
            interference_rate=interference_rate,
            recall_by_category=by_category,
            total_train_events=len(self.train_events),
            total_test_queries=len(self.test_queries),
            wall_time_seconds=wall_time,
        )
