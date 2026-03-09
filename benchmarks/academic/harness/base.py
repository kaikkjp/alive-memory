"""Base interfaces for the academic benchmark harness.

Defines the contract between dataset adapters (LoCoMo, LongMemEval, etc.)
and memory system adapters (alive, rag, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ConversationTurn:
    """A single turn in a conversation history."""

    role: str  # "user" | "assistant" | "system"
    content: str
    turn_id: int
    session_id: str = ""
    timestamp: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class MemoryQuery:
    """A query the memory system must answer using stored history."""

    query_id: str
    question: str
    category: str  # benchmark-specific category
    session_id: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class GroundTruth:
    """Expected answer for a memory query."""

    query_id: str
    answer: str
    category: str
    evidence: list[str] = field(default_factory=list)  # supporting conversation turns
    metadata: dict = field(default_factory=dict)


@dataclass
class EvalResult:
    """Result of evaluating a single query."""

    query_id: str
    category: str
    predicted: str
    expected: str
    scores: dict[str, float] = field(default_factory=dict)  # metric_name -> score
    metadata: dict = field(default_factory=dict)


@dataclass
class SystemMetrics:
    """Resource usage collected during a benchmark run."""

    total_llm_calls: int = 0
    total_tokens: int = 0
    total_latency_ms: float = 0.0
    query_latencies_ms: list[float] = field(default_factory=list)
    ingest_latencies_ms: list[float] = field(default_factory=list)
    consolidate_latencies_ms: list[float] = field(default_factory=list)
    storage_bytes: int = 0
    memory_count: int = 0

    @property
    def median_query_latency_ms(self) -> float:
        if not self.query_latencies_ms:
            return 0.0
        s = sorted(self.query_latencies_ms)
        return s[len(s) // 2]

    @property
    def p95_query_latency_ms(self) -> float:
        if not self.query_latencies_ms:
            return 0.0
        s = sorted(self.query_latencies_ms)
        return s[int(len(s) * 0.95)]

    @property
    def median_consolidate_latency_ms(self) -> float:
        if not self.consolidate_latencies_ms:
            return 0.0
        s = sorted(self.consolidate_latencies_ms)
        return s[len(s) // 2]

    @property
    def p95_consolidate_latency_ms(self) -> float:
        if not self.consolidate_latencies_ms:
            return 0.0
        s = sorted(self.consolidate_latencies_ms)
        return s[int(len(s) * 0.95)]


@dataclass
class BenchmarkRunResult:
    """Complete result from running one system on one benchmark."""

    system_id: str
    benchmark_id: str
    eval_results: list[EvalResult] = field(default_factory=list)
    aggregate_scores: dict[str, float] = field(default_factory=dict)
    scores_by_category: dict[str, dict[str, float]] = field(default_factory=dict)
    system_metrics: SystemMetrics = field(default_factory=SystemMetrics)
    config: dict = field(default_factory=dict)
    seed: int = 42

    def overall_score(self) -> float:
        """Return the primary aggregate score."""
        for key in ("f1", "accuracy", "score", "task_completion"):
            if key in self.aggregate_scores:
                return self.aggregate_scores[key]
        if self.aggregate_scores:
            return next(iter(self.aggregate_scores.values()))
        return 0.0


class DatasetAdapter(ABC):
    """Loads an academic benchmark dataset and provides conversations + queries."""

    @property
    @abstractmethod
    def benchmark_id(self) -> str:
        """Unique identifier for this benchmark (e.g., 'locomo', 'longmemeval')."""
        ...

    @abstractmethod
    async def load(self, data_dir: str, split: str = "test") -> None:
        """Load dataset from disk. Download if not present."""
        ...

    @abstractmethod
    def get_sessions(self) -> list[list[ConversationTurn]]:
        """Return conversation sessions (list of turn lists)."""
        ...

    @abstractmethod
    def get_queries(self) -> list[MemoryQuery]:
        """Return evaluation queries."""
        ...

    @abstractmethod
    def get_ground_truth(self) -> dict[str, GroundTruth]:
        """Return ground truth keyed by query_id."""
        ...

    @abstractmethod
    async def evaluate(
        self,
        predictions: dict[str, str],
        ground_truth: dict[str, GroundTruth],
    ) -> list[EvalResult]:
        """Score predictions against ground truth using benchmark-native metrics."""
        ...

    def get_categories(self) -> list[str]:
        """Return distinct query categories in this benchmark."""
        return list({q.category for q in self.get_queries()})


class MemorySystemAdapter(ABC):
    """Wraps a memory system for use in the academic benchmark harness.

    Different from benchmarks.adapters.base.MemoryAdapter — this interface
    is designed for the academic benchmarks which operate on conversation
    turns and natural language queries rather than event streams.
    """

    @property
    @abstractmethod
    def system_id(self) -> str:
        """Unique identifier for this system."""
        ...

    @abstractmethod
    async def setup(self, config: dict) -> None:
        """Initialize the memory system."""
        ...

    @abstractmethod
    async def add_conversation(self, turns: list[ConversationTurn]) -> None:
        """Ingest a conversation session into memory."""
        ...

    @abstractmethod
    async def answer_query(
        self,
        query: MemoryQuery,
        llm_config: dict,
    ) -> str:
        """Use stored memory to answer a query. Returns the answer string."""
        ...

    @abstractmethod
    async def get_metrics(self) -> SystemMetrics:
        """Return current resource usage metrics."""
        ...

    async def consolidate(self) -> None:
        """Run any maintenance/consolidation. No-op by default."""
        pass

    async def reset(self) -> None:
        """Clear all stored memory. Called between benchmark instances."""
        pass

    async def teardown(self) -> None:
        """Cleanup resources."""
        pass
