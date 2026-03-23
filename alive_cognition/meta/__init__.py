"""Meta-cognition: self-tuning parameter adjustments.

Part of alive_cognition (moved from alive_memory.meta).
"""

from alive_cognition.meta.controller import (
    Experiment,
    HardFloor,
    MetricTarget,
    classify_outcome,
    compute_adaptive_cooldown,
    request_correction,
    run_meta_controller,
)
from alive_cognition.meta.evaluation import (
    detect_side_effects,
    evaluate_experiment,
    evaluate_pending_experiments,
)
from alive_cognition.meta.protocols import DriveProvider, MetricsProvider
from alive_cognition.meta.review import (
    ReviewResult,
    StabilityReport,
    review_self_modifications,
    review_trait_stability,
    run_meta_review,
)

__all__ = [
    "run_meta_controller",
    "classify_outcome",
    "compute_adaptive_cooldown",
    "request_correction",
    "evaluate_experiment",
    "evaluate_pending_experiments",
    "detect_side_effects",
    "run_meta_review",
    "review_trait_stability",
    "review_self_modifications",
    "MetricTarget",
    "Experiment",
    "HardFloor",
    "MetricsProvider",
    "DriveProvider",
    "StabilityReport",
    "ReviewResult",
]
