"""Autotune data types."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExpectedRecall:
    """Expected recall results for a scenario turn."""

    must_contain: list[str] = field(default_factory=list)
    must_not_contain: list[str] = field(default_factory=list)
    min_results: int = 1


@dataclass
class ScenarioTurn:
    """A single turn in a scenario."""

    role: str  # "user" or "system"
    action: str = "intake"  # "intake", "recall", "advance_time", "consolidate"
    content: str = ""
    simulated_time: str | None = None  # ISO 8601
    advance_seconds: int = 0
    metadata: dict = field(default_factory=dict)
    expected_recall: ExpectedRecall | None = None


@dataclass
class Scenario:
    """A test scenario for autotune."""

    name: str
    description: str
    category: str
    turns: list[ScenarioTurn]
    setup_config: dict | None = None


@dataclass
class RecallResult:
    """Result of a recall turn during simulation."""

    turn_index: int
    query: str
    recalled_text: str  # flattened recall context
    expected: ExpectedRecall
    num_results: int = 0  # total recall hits
    elapsed_ms: int = 0


@dataclass
class SimulationResult:
    """Result of running one scenario against one config."""

    scenario_name: str
    recall_results: list[RecallResult] = field(default_factory=list)
    moments_recorded: int = 0
    moments_rejected: int = 0
    elapsed_real_ms: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class MemoryScore:
    """Scores from evaluating a simulation result."""

    recall_precision: float = 0.0
    recall_completeness: float = 0.0
    intake_acceptance_rate: float = 0.0
    dedup_accuracy: float = 0.0
    decay_accuracy: float = 0.0
    recall_latency_ms: float = 0.0

    @property
    def composite(self) -> float:
        """Single optimization target. Lower = better."""
        quality = (
            0.35 * self.recall_completeness
            + 0.30 * self.recall_precision
            + 0.15 * self.dedup_accuracy
            + 0.10 * self.decay_accuracy
            + 0.10 * self.intake_acceptance_rate
        )
        latency_penalty = min(self.recall_latency_ms / 1000.0, 1.0) * 0.05
        return 1.0 - quality + latency_penalty


@dataclass
class ExperimentRecord:
    """Record of a single autotune experiment."""

    iteration: int
    config_snapshot: dict
    config_diff: dict
    strategy: str
    scores: dict[str, MemoryScore] = field(default_factory=dict)
    composite: float = 1.0
    is_best: bool = False
    elapsed_seconds: float = 0.0
    timestamp: str = ""


@dataclass
class AutotuneConfig:
    """Configuration for the autotune engine."""

    budget: int = 50
    scenarios: str = "builtin"
    scoring_weights: dict | None = None
    seed: int = 42
    verbose: bool = True


@dataclass
class AutotuneResult:
    """Result of an autotune run."""

    best_config: dict = field(default_factory=dict)
    baseline_composite: float = 1.0
    best_composite: float = 1.0
    improvement_pct: float = 0.0
    experiments: list[ExperimentRecord] = field(default_factory=list)
    total_iterations: int = 0
    elapsed_seconds: float = 0.0
