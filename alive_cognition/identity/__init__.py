"""Identity: persistent self-model, drift detection, evolution.

Part of alive_cognition (moved from alive_memory.identity).
"""

from alive_cognition.identity.drift import (
    BehavioralBaseline,
    DriftConfig,
    DriftDetector,
    DriftMetric,
    DriftReport,
    DriftResult,
    MetricResult,
    ScalarDriftMetric,
    TVDMetric,
    detect_drift,
    scalar_drift,
    tvd,
)
from alive_cognition.identity.evolution import (
    CorrectionProvider,
    EvolutionAction,
    EvolutionDecision,
    GuardRailConfig,
    IdentityEvolution,
    apply_decision,
    evaluate_drift,
)
from alive_cognition.identity.history import (
    get_history,
    get_trait_timeline,
    summarize_development,
)
from alive_cognition.identity.self_model import (
    SelfModelManager,
    TraitConfig,
    get_self_model,
    snapshot,
    update_behavioral_summary,
    update_traits,
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
