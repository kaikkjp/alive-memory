"""Concurrent latency runner — measures performance under parallel load.

Uses asyncio.gather to run N parallel ingest+recall operations,
measuring throughput (ops/sec) and tail latency under contention.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path

from benchmarks.adapters.base import BenchEvent, MemoryAdapter
from benchmarks.runner import load_jsonl


@dataclass
class ConcurrentLatencyResult:
    """Result from concurrent stress test."""

    system_id: str
    throughput: float  # operations per second
    p50_ms: float
    p95_ms: float
    p99_ms: float
    p999_ms: float
    error_rate: float
    concurrency: int
    total_ops: int
    degradation_ratio: float  # concurrent p95 / sequential p95
    wall_time_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "system_id": self.system_id,
            "throughput": self.throughput,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "p999_ms": self.p999_ms,
            "error_rate": self.error_rate,
            "concurrency": self.concurrency,
            "total_ops": self.total_ops,
            "degradation_ratio": self.degradation_ratio,
            "wall_time_seconds": self.wall_time_seconds,
        }

    def save(self, path: str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2))


class ConcurrentRunner:
    """Runs concurrent stress tests on a memory adapter."""

    def __init__(
        self,
        stream_path: str,
        concurrency: int = 10,
        max_cycles: int | None = None,
    ):
        self.events = load_jsonl(stream_path)
        self.concurrency = concurrency

        if max_cycles:
            self.events = [e for e in self.events if e["cycle"] <= max_cycles]

    async def _single_op(
        self,
        adapter: MemoryAdapter,
        event: BenchEvent,
        query: str,
    ) -> tuple[float, float, str | None]:
        """Run a single ingest + recall pair. Returns (ingest_time, recall_time, error)."""
        error = None
        try:
            t0 = time.perf_counter()
            await adapter.ingest(event)
            ingest_time = time.perf_counter() - t0

            t0 = time.perf_counter()
            await adapter.recall(query, limit=5)
            recall_time = time.perf_counter() - t0
        except Exception as e:
            ingest_time = 0.0
            recall_time = 0.0
            error = str(e)

        return ingest_time, recall_time, error

    async def run(
        self,
        adapter: MemoryAdapter,
        system_id: str,
    ) -> ConcurrentLatencyResult:
        """Run concurrent stress test."""
        await adapter.setup({})

        # First: sequential baseline (measure p95 without contention)
        sequential_latencies = []
        baseline_count = min(100, len(self.events))
        for i in range(baseline_count):
            event = BenchEvent.from_dict(self.events[i])
            t0 = time.perf_counter()
            await adapter.ingest(event)
            await adapter.recall(event.content[:50], limit=5)
            sequential_latencies.append(time.perf_counter() - t0)

        sequential_latencies.sort()
        seq_p95 = sequential_latencies[int(len(sequential_latencies) * 0.95)] * 1000 if sequential_latencies else 1.0

        # Reset adapter for concurrent test
        await adapter.teardown()
        await adapter.setup({})

        wall_start = time.monotonic()

        all_latencies = []
        errors = 0
        total_ops = 0

        # Process events in concurrent batches
        batch_start = baseline_count  # skip baseline events
        while batch_start < len(self.events):
            batch_end = min(batch_start + self.concurrency, len(self.events))
            batch_events = self.events[batch_start:batch_end]

            tasks = []
            for event_dict in batch_events:
                event = BenchEvent.from_dict(event_dict)
                query = event.content[:50] if event.content else "recall"
                tasks.append(self._single_op(adapter, event, query))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for r in results:
                total_ops += 1
                if isinstance(r, Exception):
                    errors += 1
                else:
                    ingest_t, recall_t, err = r
                    if err:
                        errors += 1
                    else:
                        all_latencies.append((ingest_t + recall_t) * 1000)  # ms

            batch_start = batch_end

            if total_ops % 500 == 0:
                print(f"  [{system_id}] {total_ops} ops completed")

        wall_time = time.monotonic() - wall_start
        await adapter.teardown()

        # Compute percentiles
        if all_latencies:
            all_latencies.sort()
            n = len(all_latencies)
            p50 = all_latencies[n // 2]
            p95 = all_latencies[int(n * 0.95)]
            p99 = all_latencies[int(n * 0.99)]
            p999 = all_latencies[min(int(n * 0.999), n - 1)]
        else:
            p50 = p95 = p99 = p999 = 0.0

        throughput = total_ops / wall_time if wall_time > 0 else 0.0
        degradation = p95 / seq_p95 if seq_p95 > 0 else 0.0

        return ConcurrentLatencyResult(
            system_id=system_id,
            throughput=throughput,
            p50_ms=p50,
            p95_ms=p95,
            p99_ms=p99,
            p999_ms=p999,
            error_rate=errors / max(total_ops, 1),
            concurrency=self.concurrency,
            total_ops=total_ops,
            degradation_ratio=degradation,
            wall_time_seconds=wall_time,
        )
