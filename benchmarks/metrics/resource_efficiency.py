"""Metric 6: Resource Efficiency — what does each system cost to run?"""

from dataclasses import dataclass

from benchmarks.runner import BenchmarkResult

# Pricing as of March 2026
PRICING = {
    "claude-haiku-4-5-20251001": {"input": 0.25, "output": 1.25},  # per MTok
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "default": {"input": 1.0, "output": 5.0},
}


@dataclass
class ResourceEfficiencyResult:
    total_llm_calls: int
    total_tokens: int
    estimated_cost_usd: float
    storage_bytes_final: int
    storage_bytes_per_event: float
    avg_ingest_latency_ms: float
    avg_recall_latency_ms: float
    avg_consolidation_latency_ms: float
    memory_count_final: int
    events_per_memory: float  # compression ratio


def compute_resource_efficiency(
    result: BenchmarkResult,
    model: str = "default",
) -> ResourceEfficiencyResult:
    """Compute resource efficiency from benchmark result."""
    stats = result.final_stats
    lat = result.latencies

    total_tokens = stats.total_tokens if stats else 0
    total_llm = stats.total_llm_calls if stats else 0
    storage = stats.storage_bytes if stats else 0
    mem_count = stats.memory_count if stats else 0

    # Cost estimate: assume 50/50 input/output split (rough)
    pricing = PRICING.get(model, PRICING["default"])
    cost = total_tokens / 1_000_000 * (pricing["input"] + pricing["output"]) / 2

    # Latency averages
    def avg_ms(key: str) -> float:
        vals = lat.get(key, [])
        return (sum(vals) / len(vals) * 1000) if vals else 0.0

    # Compression ratio
    events_per_mem = result.total_events / mem_count if mem_count > 0 else 0.0
    bytes_per_event = storage / result.total_events if result.total_events > 0 else 0.0

    return ResourceEfficiencyResult(
        total_llm_calls=total_llm,
        total_tokens=total_tokens,
        estimated_cost_usd=cost,
        storage_bytes_final=storage,
        storage_bytes_per_event=bytes_per_event,
        avg_ingest_latency_ms=avg_ms("ingest"),
        avg_recall_latency_ms=avg_ms("recall"),
        avg_consolidation_latency_ms=avg_ms("consolidate"),
        memory_count_final=mem_count,
        events_per_memory=events_per_mem,
    )
