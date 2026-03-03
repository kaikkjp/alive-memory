"""Meta-cognition: self-tuning parameter adjustments."""

from alive_memory.meta.controller import (
    run_meta_controller,
    classify_outcome,
    compute_adaptive_cooldown,
    MetricTarget,
    Experiment,
)
from alive_memory.meta.evaluation import evaluate_experiment, detect_side_effects

__all__ = [
    "run_meta_controller",
    "classify_outcome",
    "compute_adaptive_cooldown",
    "evaluate_experiment",
    "detect_side_effects",
    "MetricTarget",
    "Experiment",
]
