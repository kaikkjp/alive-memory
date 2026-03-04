"""Identity: persistent self-model, drift detection, evolution."""

from alive_memory.identity.self_model import (
    TraitConfig,
    SelfModelManager,
    get_self_model,
    update_traits,
    update_behavioral_summary,
    snapshot,
)
from alive_memory.identity.drift import (
    DriftConfig,
    DriftMetric,
    DriftDetector,
    DriftResult,
    DriftReport,
    BehavioralBaseline,
    MetricResult,
    TVDMetric,
    ScalarDriftMetric,
    tvd,
    scalar_drift,
    detect_drift,
)
from alive_memory.identity.evolution import (
    EvolutionAction,
    EvolutionDecision,
    GuardRailConfig,
    CorrectionProvider,
    IdentityEvolution,
    evaluate_drift,
    apply_decision,
)
from alive_memory.identity.history import (
    get_history,
    get_trait_timeline,
    summarize_development,
)

__all__ = [
    # self_model
    "TraitConfig",
    "SelfModelManager",
    "get_self_model",
    "update_traits",
    "update_behavioral_summary",
    "snapshot",
    # drift
    "DriftConfig",
    "DriftMetric",
    "DriftDetector",
    "DriftResult",
    "DriftReport",
    "BehavioralBaseline",
    "MetricResult",
    "TVDMetric",
    "ScalarDriftMetric",
    "tvd",
    "scalar_drift",
    "detect_drift",
    # evolution
    "EvolutionAction",
    "EvolutionDecision",
    "GuardRailConfig",
    "CorrectionProvider",
    "IdentityEvolution",
    "evaluate_drift",
    "apply_decision",
    # history
    "get_history",
    "get_trait_timeline",
    "summarize_development",
]
