"""Evolve data types — richer evaluation types for source-level memory optimization."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FailureCategory(Enum):
    """Categories of memory recall failures that evolve targets."""

    SHORT_TERM_RECALL = "short_term_recall"
    CROSS_SESSION_RECALL = "cross_session_recall"
    CONSOLIDATION_SURVIVAL = "consolidation_survival"
    NOISE_DECAY = "noise_decay"
    CONTRADICTION_HANDLING = "contradiction_handling"
    HIGH_VOLUME_STRESS = "high_volume_stress"
    EMOTIONAL_WEIGHTING = "emotional_weighting"
    RELATIONAL_RECALL = "relational_recall"


# ---------------------------------------------------------------------------
# Eval case building blocks
# ---------------------------------------------------------------------------


@dataclass
class ConversationTurn:
    """A single turn in a simulated conversation."""

    turn: int
    time: str  # ISO 8601
    role: str  # "user" or "assistant"
    content: str


@dataclass
class TimeGap:
    """A time gap injected between conversation turns."""

    after_turn: int
    skip_to: str  # ISO 8601 timestamp to advance the clock to
    consolidation_expected: bool = True


@dataclass
class EvalQuery:
    """A recall query issued after conversation replay."""

    time: str  # ISO 8601 — the simulated time of the query
    query: str
    ground_truth: list[str]
    bonus_inferences: list[str] = field(default_factory=list)
    should_not_recall: list[str] = field(default_factory=list)
    expected_emotional_weight: str | None = None


@dataclass
class EvalCase:
    """A complete evaluation case: conversation + gaps + queries."""

    id: str
    category: str
    difficulty: int
    difficulty_axes: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    conversation: list[ConversationTurn] = field(default_factory=list)
    time_gaps: list[TimeGap] = field(default_factory=list)
    queries: list[EvalQuery] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


@dataclass
class RecallScore:
    """Per-query recall quality score."""

    precision: float = 0.0
    completeness: float = 0.0
    noise_rejection: float = 0.0
    ranking_quality: float = 0.0
    latency_ms: float = 0.0

    @property
    def composite(self) -> float:
        """Single scalar score. Lower = better (mirrors autotune convention)."""
        quality = (
            0.35 * self.completeness
            + 0.25 * self.precision
            + 0.20 * self.noise_rejection
            + 0.15 * self.ranking_quality
        )
        latency_factor = min(max(self.latency_ms - 200, 0) / 800, 1.0)
        latency_penalty = 0.05 * latency_factor
        return 1.0 - quality + latency_penalty


@dataclass
class CaseResult:
    """Result of running a single eval case."""

    case_id: str
    category: str
    difficulty: int
    score: RecallScore = field(default_factory=RecallScore)
    per_query_scores: list[RecallScore] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class SplitResult:
    """Aggregate results for one data split (train / held-out / production)."""

    name: str
    case_results: list[CaseResult] = field(default_factory=list)
    pass_count: int = 0
    fail_count: int = 0
    _aggregate_score: float | None = field(default=None, repr=False)

    @property
    def aggregate_score(self) -> float:
        """Mean category-adjusted score across cases. 1.0 (worst) when empty.

        When set explicitly by the runner (via ``score_case()`` adjustments),
        returns that stored value.  Otherwise falls back to raw composite mean.
        """
        if self._aggregate_score is not None:
            return self._aggregate_score
        if not self.case_results:
            return 1.0
        return sum(cr.score.composite for cr in self.case_results) / len(
            self.case_results
        )

    @aggregate_score.setter
    def aggregate_score(self, value: float) -> None:
        self._aggregate_score = value


@dataclass
class EvolveScore:
    """Composite score across train / held-out / production splits."""

    train: SplitResult = field(default_factory=lambda: SplitResult(name="train"))
    held_out: SplitResult = field(default_factory=lambda: SplitResult(name="held_out"))
    production: SplitResult = field(
        default_factory=lambda: SplitResult(name="production")
    )

    @property
    def composite(self) -> float:
        """Weighted mean across splits. Lower = better."""
        return (
            0.4 * self.train.aggregate_score
            + 0.4 * self.held_out.aggregate_score
            + 0.2 * self.production.aggregate_score
        )

    @property
    def overfitting_signal(self) -> float:
        """Positive value indicates potential overfitting to training data."""
        return self.train.aggregate_score - self.held_out.aggregate_score


# ---------------------------------------------------------------------------
# Config & result records
# ---------------------------------------------------------------------------


@dataclass
class EvolveConfig:
    """Configuration for an evolve run."""

    budget: int = 10
    target_files: list[str] = field(default_factory=list)
    eval_suite_path: str = ""
    verbose: bool = True


@dataclass
class IterationRecord:
    """Record of a single evolve iteration."""

    iteration: int
    score: EvolveScore | None = None
    promoted: bool = False
    failure_analysis: str = ""
    source_changes: dict = field(default_factory=dict)
    elapsed_seconds: float = 0.0
    timestamp: str = ""


@dataclass
class EvolveResult:
    """Result of a complete evolve run."""

    best_score: EvolveScore | None = None
    baseline_score: EvolveScore | None = None
    iterations: list[IterationRecord] = field(default_factory=list)
    source_diffs: dict = field(default_factory=dict)
    total_iterations: int = 0
    elapsed_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Per-category scoring adjustments
# ---------------------------------------------------------------------------

CATEGORY_SCORING_ADJUSTMENTS: dict[str, dict] = {
    "contradiction_handling": {"recency_weight": 0.3},
    "high_volume_stress": {"latency_penalty_weight": 0.15},
    "emotional_weighting": {"ranking_boost": True},
    "relational_recall": {"entity_expansion_bonus": True},
    "noise_decay": {"noise_rejection_weight": 0.35},
}
