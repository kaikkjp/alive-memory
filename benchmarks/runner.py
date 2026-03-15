"""Benchmark runner — drives event ingestion, measurement, and result collection.

Processes an event stream through a MemoryAdapter, pausing at measurement
points to evaluate recall quality, and collecting latency/resource data.
"""

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from benchmarks.adapters.base import BenchEvent, MemoryAdapter, SystemStats
from benchmarks.scoring.hard_truth import (
    ScoredRecall,
    aggregate_by_category,
    aggregate_scores,
    check_traceability,
    score_contradiction,
    score_entity_confusion,
    score_negative_recall,
    score_recall,
)


@dataclass
class CycleMetrics:
    """Metrics snapshot at a single measurement point."""

    cycle: int
    recall_scores: list[ScoredRecall] = field(default_factory=list)
    recall_summary: dict = field(default_factory=dict)
    recall_by_category: dict = field(default_factory=dict)
    contradiction_results: list[dict] = field(default_factory=list)
    stats: SystemStats | None = None
    identity_state: dict | None = None
    adapter_data: dict = field(default_factory=dict)
    traceability_results: list[dict] = field(default_factory=list)
    entity_confusion_results: list[dict] = field(default_factory=list)
    tier_distribution: dict = field(default_factory=dict)


@dataclass
class BenchmarkResult:
    """Complete result from a single system's benchmark run."""

    system_id: str
    stream_name: str
    seed: int
    final_metrics: CycleMetrics | None = None
    metrics_over_time: list[tuple[int, CycleMetrics]] = field(default_factory=list)
    final_stats: SystemStats | None = None
    latencies: dict = field(default_factory=lambda: {
        "ingest": [], "recall": [], "consolidate": [],
    })
    total_events: int = 0
    wall_time_seconds: float = 0.0

    def to_dict(self) -> dict:
        """Serialize to JSON-safe dict."""
        d = {
            "system_id": self.system_id,
            "stream_name": self.stream_name,
            "seed": self.seed,
            "total_events": self.total_events,
            "wall_time_seconds": self.wall_time_seconds,
        }

        if self.final_stats:
            d["final_stats"] = asdict(self.final_stats)

        if self.final_metrics:
            fm = {
                "cycle": self.final_metrics.cycle,
                "recall_summary": self.final_metrics.recall_summary,
                "recall_by_category": self.final_metrics.recall_by_category,
                "contradiction_results": self.final_metrics.contradiction_results,
            }
            if self.final_metrics.traceability_results:
                fm["traceability_results"] = self.final_metrics.traceability_results
            if self.final_metrics.entity_confusion_results:
                fm["entity_confusion_results"] = self.final_metrics.entity_confusion_results
            if self.final_metrics.tier_distribution:
                fm["tier_distribution"] = self.final_metrics.tier_distribution
            if self.final_metrics.adapter_data:
                fm["adapter_data"] = self.final_metrics.adapter_data
            d["final_metrics"] = fm

        d["metrics_over_time"] = []
        for cycle, m in self.metrics_over_time:
            point = {
                "cycle": cycle,
                "recall_summary": m.recall_summary,
                "recall_by_category": m.recall_by_category,
                "stats": asdict(m.stats) if m.stats else None,
            }
            if m.tier_distribution:
                point["tier_distribution"] = m.tier_distribution
            d["metrics_over_time"].append(point)

        # Latency summaries (not raw arrays — too large)
        d["latencies"] = {}
        for key, values in self.latencies.items():
            if values:
                sorted_v = sorted(values)
                n = len(sorted_v)
                d["latencies"][key] = {
                    "count": n,
                    "mean_ms": sum(sorted_v) / n * 1000,
                    "p50_ms": sorted_v[n // 2] * 1000,
                    "p95_ms": sorted_v[int(n * 0.95)] * 1000,
                    "p99_ms": sorted_v[int(n * 0.99)] * 1000,
                    "p999_ms": sorted_v[min(int(n * 0.999), n - 1)] * 1000,
                    "max_ms": sorted_v[-1] * 1000,
                }
            else:
                d["latencies"][key] = {"count": 0}

        return d

    def save(self, path: str) -> None:
        """Save result to JSON file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2))


def load_jsonl(path: str) -> list[dict]:
    """Load a JSONL file into a list of dicts."""
    items = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def load_ground_truth(path: str) -> dict[str, dict]:
    """Load ground truth JSONL, keyed by query_id."""
    items = load_jsonl(path)
    return {item["query_id"]: item for item in items}


class BenchmarkRunner:
    """Runs a benchmark stream through a memory adapter and collects metrics."""

    def __init__(
        self,
        stream_path: str,
        query_path: str,
        ground_truth_path: str,
        consolidation_interval: int = 500,
        measurement_points: list[int] | None = None,
        max_cycles: int | None = None,
        primary_users: list[str] | None = None,
    ):
        self.events = load_jsonl(stream_path)
        self.queries = load_jsonl(query_path)
        self.ground_truth = load_ground_truth(ground_truth_path)
        self.consolidation_interval = consolidation_interval
        self.measurement_points = set(
            measurement_points or [100, 500, 1000, 2000, 5000, 10000]
        )
        self.max_cycles = max_cycles
        self.primary_users = primary_users or []
        self._content_index: set[str] | None = None

        if self.max_cycles:
            self.events = [e for e in self.events if e["cycle"] <= self.max_cycles]
            self.measurement_points = {
                p for p in self.measurement_points if p <= self.max_cycles
            }

    async def run(
        self,
        adapter: MemoryAdapter,
        system_id: str,
        seed: int = 42,
        stream_name: str = "",
    ) -> BenchmarkResult:
        """Run the full benchmark for one memory system."""
        await adapter.setup({"seed": seed})

        result = BenchmarkResult(
            system_id=system_id,
            stream_name=stream_name,
            seed=seed,
            total_events=len(self.events),
        )

        wall_start = time.monotonic()

        for i, event_dict in enumerate(self.events):
            cycle = event_dict["cycle"]
            event = BenchEvent.from_dict(event_dict)

            # --- Ingest ---
            t0 = time.perf_counter()
            await adapter.ingest(event)
            result.latencies["ingest"].append(time.perf_counter() - t0)

            # --- Consolidation ---
            if cycle > 0 and cycle % self.consolidation_interval == 0:
                t0 = time.perf_counter()
                await adapter.consolidate()
                result.latencies["consolidate"].append(time.perf_counter() - t0)

            # --- Measurement point ---
            if cycle in self.measurement_points:
                metrics = await self._measure(adapter, cycle, result.latencies)
                result.metrics_over_time.append((cycle, metrics))

                stats = metrics.stats
                f1 = metrics.recall_summary.get("f1", 0.0)
                mem_count = stats.memory_count if stats else 0
                print(
                    f"  [{system_id}] cycle {cycle}: "
                    f"{mem_count} memories, F1={f1:.3f}"
                )

            # Progress indicator for long runs
            if (i + 1) % 1000 == 0:
                elapsed = time.monotonic() - wall_start
                rate = (i + 1) / elapsed
                remaining = (len(self.events) - i - 1) / rate
                print(
                    f"  [{system_id}] {i + 1}/{len(self.events)} events "
                    f"({rate:.0f} evt/s, ~{remaining:.0f}s remaining)"
                )

        # --- Final measurement ---
        if self.events:
            final_cycle = self.events[-1]["cycle"]
            result.final_metrics = await self._measure(
                adapter, final_cycle, result.latencies
            )
            result.final_stats = await adapter.get_stats()

        result.wall_time_seconds = time.monotonic() - wall_start

        await adapter.teardown()

        return result

    def _get_content_index(self, cycle: int) -> set[str]:
        """Build content index for traceability checks up to given cycle."""
        from benchmarks.scoring.hard_truth import build_content_index
        return build_content_index(self.events, cycle)

    async def _measure(
        self,
        adapter: MemoryAdapter,
        cycle: int,
        latencies: dict,
    ) -> CycleMetrics:
        """Run queries for this cycle point and compute metrics."""
        # Get queries for this cycle
        cycle_queries = [q for q in self.queries if q["cycle"] == cycle]
        if not cycle_queries:
            # Use rolling queries
            cycle_queries = [q for q in self.queries if q.get("rolling", False)]

        metrics = CycleMetrics(cycle=cycle)
        recall_scores = []
        contradiction_results = []
        traceability_results = []
        entity_confusion_results = []
        tier_counts: dict[str, int] = {}

        # Build content index for traceability (lazily)
        content_index = self._get_content_index(cycle)

        for q in cycle_queries:
            query_id = q["query_id"]
            category = q["category"]
            gt = self.ground_truth.get(query_id, {})

            # Recall
            t0 = time.perf_counter()
            results = await adapter.recall(q["query"], limit=5)
            latencies.setdefault("recall", []).append(time.perf_counter() - t0)

            # Traceability check for each result
            for r in results:
                trace = check_traceability(r.content, content_index)
                traceability_results.append({
                    "query_id": query_id,
                    **trace,
                })

            # Tier distribution from result metadata
            for r in results:
                tier = r.metadata.get("tier", "unknown")
                tier_counts[tier] = tier_counts.get(tier, 0) + 1

            # Entity confusion check for entity_tracking queries
            if category == "entity_tracking" and self.primary_users:
                # Extract queried user from the query text
                query_text = q["query"].lower()
                query_user = ""
                for u in self.primary_users:
                    if u.lower() in query_text:
                        query_user = u
                        break
                if query_user:
                    confusion = score_entity_confusion(
                        query_id, query_user, results, self.primary_users,
                    )
                    entity_confusion_results.append(confusion)

            # Score based on category
            if category == "negative_recall":
                forbidden = gt.get("forbidden_memories", q.get("expected_memories", []))
                scored = score_negative_recall(query_id, results, forbidden)
                recall_scores.append(scored)
            elif category == "forget_verification":
                expected = gt.get("expected_memories", q.get("expected_memories", []))
                scored = score_recall(query_id, category, results, expected)
                recall_scores.append(scored)
            elif category == "contradiction" or category == "fact_update":
                expected = gt.get("expected_memories", q.get("expected_memories", []))
                scored = score_recall(query_id, category, results, expected)
                recall_scores.append(scored)

                # Also score contradiction specifics
                current = gt.get("current_fact", "")
                stale = gt.get("stale_fact", "")
                if current and stale:
                    contra = score_contradiction(
                        query_id, results, current, stale
                    )
                    contradiction_results.append(contra)
            else:
                expected = gt.get("expected_memories", q.get("expected_memories", []))
                scored = score_recall(query_id, category, results, expected)
                recall_scores.append(scored)

        metrics.recall_scores = recall_scores
        metrics.recall_summary = aggregate_scores(recall_scores)
        metrics.recall_by_category = aggregate_by_category(recall_scores)
        metrics.contradiction_results = contradiction_results
        metrics.traceability_results = traceability_results
        metrics.entity_confusion_results = entity_confusion_results
        metrics.tier_distribution = tier_counts
        metrics.stats = await adapter.get_stats()
        metrics.identity_state = await adapter.get_state()
        metrics.adapter_data = await adapter.get_adapter_data()

        return metrics
