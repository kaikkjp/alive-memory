"""Identity: persistent self-model, drift detection, evolution."""

from alive_memory.identity.self_model import get_self_model, update_traits, snapshot
from alive_memory.identity.drift import detect_drift, DriftReport
from alive_memory.identity.evolution import evaluate_drift, apply_decision, EvolutionDecision
from alive_memory.identity.history import get_history, get_trait_timeline, summarize_development

__all__ = [
    "get_self_model",
    "update_traits",
    "snapshot",
    "detect_drift",
    "DriftReport",
    "evaluate_drift",
    "apply_decision",
    "EvolutionDecision",
    "get_history",
    "get_trait_timeline",
    "summarize_development",
]
