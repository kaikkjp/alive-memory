"""Tests for identity (drift, evolution, history) and meta (controller, evaluation) modules."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone

import pytest

from alive_memory.config import AliveConfig
from alive_memory.identity.drift import DriftReport, detect_drift
from alive_memory.identity.evolution import EvolutionDecision, apply_decision, evaluate_drift
from alive_memory.identity.history import get_history, get_trait_timeline, summarize_development
from alive_memory.identity.self_model import get_self_model, snapshot, update_behavioral_summary, update_traits
from alive_memory.meta.controller import Experiment, MetricTarget, classify_outcome, compute_adaptive_cooldown, run_meta_controller
from alive_memory.meta.evaluation import detect_side_effects, evaluate_experiment
from alive_memory.storage.sqlite import SQLiteStorage


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
async def storage(tmp_db):
    s = SQLiteStorage(tmp_db)
    await s.initialize()
    yield s
    await s.close()


# ── Identity: Self-Model ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_self_model_default(storage):
    model = await get_self_model(storage)
    assert model.version == 0
    assert model.traits == {}


@pytest.mark.asyncio
async def test_update_traits(storage):
    model = await update_traits(storage, {"warmth": 0.7, "curiosity": 0.6})
    assert model.traits["warmth"] == 0.7
    assert model.traits["curiosity"] == 0.6
    assert model.version == 1


@pytest.mark.asyncio
async def test_update_traits_tracks_drift(storage):
    # Set initial traits
    await update_traits(storage, {"warmth": 0.5})
    # Update to trigger drift tracking
    model = await update_traits(storage, {"warmth": 0.8})
    assert len(model.drift_history) == 1
    assert model.drift_history[0]["trait"] == "warmth"
    assert model.drift_history[0]["delta"] == pytest.approx(0.3, abs=0.01)


@pytest.mark.asyncio
async def test_update_traits_clamps(storage):
    model = await update_traits(storage, {"extreme": 5.0})
    assert model.traits["extreme"] == 1.0

    model = await update_traits(storage, {"extreme": -5.0})
    assert model.traits["extreme"] == -1.0


@pytest.mark.asyncio
async def test_update_behavioral_summary(storage):
    model = await update_behavioral_summary(storage, "I am warm and curious.")
    assert model.behavioral_summary == "I am warm and curious."
    assert model.version == 1


@pytest.mark.asyncio
async def test_snapshot(storage):
    model = await snapshot(storage)
    assert model.snapshot_at is not None


# ── Identity: Drift Detection ──────────────────────────────────────


@pytest.mark.asyncio
async def test_detect_drift_no_history(storage):
    reports = await detect_drift(storage)
    assert reports == []


@pytest.mark.asyncio
async def test_detect_drift_below_threshold(storage):
    model = await storage.get_self_model()
    model.traits = {"warmth": 0.55}
    model.drift_history = [
        {"trait": "warmth", "delta": 0.03},
        {"trait": "warmth", "delta": 0.02},
    ]
    await storage.save_self_model(model)

    reports = await detect_drift(storage)
    assert reports == []  # magnitude 0.05 < threshold 0.15


@pytest.mark.asyncio
async def test_detect_drift_above_threshold(storage):
    model = await storage.get_self_model()
    model.traits = {"warmth": 0.8}
    model.drift_history = [
        {"trait": "warmth", "delta": 0.1},
        {"trait": "warmth", "delta": 0.1},
        {"trait": "warmth", "delta": 0.1},
    ]
    await storage.save_self_model(model)

    reports = await detect_drift(storage)
    assert len(reports) == 1
    assert reports[0].trait == "warmth"
    assert reports[0].direction == "increase"
    assert reports[0].magnitude == pytest.approx(0.3, abs=0.01)
    assert reports[0].confidence > 0


@pytest.mark.asyncio
async def test_detect_drift_mixed_directions(storage):
    model = await storage.get_self_model()
    model.traits = {"warmth": 0.5}
    model.drift_history = [
        {"trait": "warmth", "delta": 0.1},
        {"trait": "warmth", "delta": -0.08},
        {"trait": "warmth", "delta": 0.12},
        {"trait": "warmth", "delta": -0.1},
    ]
    await storage.save_self_model(model)

    # Net delta is 0.04, below threshold
    reports = await detect_drift(storage)
    assert reports == []


# ── Identity: Evolution ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evaluate_drift_accept_high_confidence(storage):
    report = DriftReport(
        trait="warmth", direction="increase", magnitude=0.3,
        old_value=0.5, new_value=0.8, confidence=0.9, window_cycles=5,
    )
    decision = await evaluate_drift(report, storage)
    assert decision.action == "accept"


@pytest.mark.asyncio
async def test_evaluate_drift_defer_low_confidence(storage):
    report = DriftReport(
        trait="warmth", direction="increase", magnitude=0.2,
        old_value=0.5, new_value=0.7, confidence=0.3, window_cycles=3,
    )
    decision = await evaluate_drift(report, storage)
    assert decision.action == "defer"


@pytest.mark.asyncio
async def test_evaluate_drift_correct_protected_trait(storage):
    report = DriftReport(
        trait="warmth", direction="decrease", magnitude=0.4,
        old_value=0.5, new_value=0.1, confidence=0.9, window_cycles=5,
    )
    protected = {"warmth": (0.3, 0.9)}
    decision = await evaluate_drift(report, storage, protected_traits=protected)
    assert decision.action == "correct"
    assert decision.correction_value == 0.3


@pytest.mark.asyncio
async def test_apply_decision_correct(storage):
    # Set initial trait
    await update_traits(storage, {"warmth": 0.1})

    decision = EvolutionDecision(
        action="correct", trait="warmth",
        reason="Too low", correction_value=0.5,
    )
    await apply_decision(decision, storage)

    model = await storage.get_self_model()
    assert model.traits["warmth"] == pytest.approx(0.5, abs=0.01)


@pytest.mark.asyncio
async def test_apply_decision_accept_is_noop(storage):
    await update_traits(storage, {"warmth": 0.8})
    decision = EvolutionDecision(
        action="accept", trait="warmth", reason="Natural growth",
    )
    await apply_decision(decision, storage)

    model = await storage.get_self_model()
    assert model.traits["warmth"] == pytest.approx(0.8, abs=0.01)


# ── Identity: History ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_history_empty(storage):
    history = await get_history(storage)
    assert history == []


@pytest.mark.asyncio
async def test_get_history_with_versions(storage):
    model = await storage.get_self_model()
    model.drift_history = [
        {"trait": "warmth", "delta": 0.1, "version": 1},
        {"trait": "warmth", "delta": 0.1, "version": 2},
        {"trait": "curiosity", "delta": -0.1, "version": 3},
    ]
    await storage.save_self_model(model)

    history = await get_history(storage, from_version=2)
    assert len(history) == 2  # versions 2 and 3


@pytest.mark.asyncio
async def test_get_trait_timeline(storage):
    model = await storage.get_self_model()
    model.drift_history = [
        {"trait": "warmth", "delta": 0.1},
        {"trait": "curiosity", "delta": -0.1},
        {"trait": "warmth", "delta": 0.05},
    ]
    await storage.save_self_model(model)

    timeline = await get_trait_timeline(storage, "warmth")
    assert len(timeline) == 2


@pytest.mark.asyncio
async def test_summarize_development(storage):
    model = await storage.get_self_model()
    model.version = 5
    model.traits = {"warmth": 0.7, "curiosity": 0.6}
    model.behavioral_summary = "Warm and curious"
    model.drift_history = [
        {"trait": "warmth", "delta": 0.1},
        {"trait": "warmth", "delta": 0.1},
        {"trait": "curiosity", "delta": -0.05},
    ]
    await storage.save_self_model(model)

    summary = await summarize_development(storage)
    assert summary["total_versions"] == 5
    assert summary["total_drift_events"] == 3
    assert summary["current_traits"]["warmth"] == 0.7
    assert len(summary["most_changed_traits"]) >= 1
    assert summary["most_changed_traits"][0][0] == "warmth"  # most changed


# ── Meta: Controller ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_meta_controller_no_targets(storage):
    experiments = await run_meta_controller(storage, {"recall_quality": 0.8}, [])
    assert experiments == []


@pytest.mark.asyncio
async def test_meta_controller_in_range(storage):
    # Pre-set parameter
    await storage.set_parameter("consolidation.decay_rate", 0.5, reason="init")

    target = MetricTarget(
        name="recall_quality", min_value=0.3, max_value=0.9,
        param_key="consolidation.decay_rate",
    )
    experiments = await run_meta_controller(
        storage, {"recall_quality": 0.6}, [target],
    )
    assert experiments == []  # 0.6 is in [0.3, 0.9]


@pytest.mark.asyncio
async def test_meta_controller_below_range(storage):
    await storage.set_parameter("consolidation.decay_rate", 0.5, reason="init")

    target = MetricTarget(
        name="recall_quality", min_value=0.5, max_value=0.9,
        param_key="consolidation.decay_rate", adjustment_step=0.1,
    )
    experiments = await run_meta_controller(
        storage, {"recall_quality": 0.3}, [target],
    )
    assert len(experiments) == 1
    assert experiments[0].new_value == pytest.approx(0.6, abs=0.01)


@pytest.mark.asyncio
async def test_meta_controller_above_range(storage):
    await storage.set_parameter("consolidation.decay_rate", 0.5, reason="init")

    target = MetricTarget(
        name="recall_quality", min_value=0.3, max_value=0.7,
        param_key="consolidation.decay_rate", adjustment_step=0.1,
    )
    experiments = await run_meta_controller(
        storage, {"recall_quality": 0.9}, [target],
    )
    assert len(experiments) == 1
    assert experiments[0].new_value == pytest.approx(0.4, abs=0.01)


# ── Meta: Evaluation ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evaluate_experiment_improved(storage):
    await storage.set_parameter("consolidation.decay_rate", 0.6, reason="test")

    exp = Experiment(
        id="exp-1", param_key="consolidation.decay_rate",
        old_value=0.5, new_value=0.6,
        target_metric="recall_quality", metric_at_change=0.3,
    )
    result = await evaluate_experiment(
        exp, {"recall_quality": 0.6}, 0.5, 0.9, storage,
    )
    assert result.outcome == "improved"
    assert result.confidence > 0.5


@pytest.mark.asyncio
async def test_evaluate_experiment_degraded_reverts(storage):
    await storage.set_parameter("consolidation.decay_rate", 0.6, reason="test")

    exp = Experiment(
        id="exp-2", param_key="consolidation.decay_rate",
        old_value=0.5, new_value=0.6,
        target_metric="recall_quality", metric_at_change=0.4,
        confidence=0.5,
    )
    result = await evaluate_experiment(
        exp, {"recall_quality": 0.2}, 0.5, 0.9, storage,
    )
    assert result.outcome == "degraded"
    assert result.confidence < 0.5  # confidence reduced

    # Should have reverted the parameter
    params = await storage.get_parameters()
    assert params["consolidation.decay_rate"] == pytest.approx(0.5, abs=0.01)


def test_detect_side_effects():
    exp = Experiment(
        id="exp-3", param_key="decay_rate",
        old_value=0.5, new_value=0.6,
        target_metric="recall_quality", metric_at_change=0.4,
    )
    before = {"recall_quality": 0.4, "identity_stability": 0.8}
    after = {"recall_quality": 0.6, "identity_stability": 0.3}
    targets = {
        "recall_quality": (0.3, 0.9),
        "identity_stability": (0.5, 1.0),
    }

    effects = detect_side_effects(exp, before, after, targets)
    assert "identity_stability" in effects


def test_detect_side_effects_none():
    exp = Experiment(
        id="exp-4", param_key="decay_rate",
        old_value=0.5, new_value=0.6,
        target_metric="recall_quality", metric_at_change=0.4,
    )
    before = {"recall_quality": 0.4, "stability": 0.7}
    after = {"recall_quality": 0.6, "stability": 0.7}
    targets = {"recall_quality": (0.3, 0.9), "stability": (0.5, 1.0)}

    effects = detect_side_effects(exp, before, after, targets)
    assert effects == []


# ── Meta: Classify Outcome (additional cases) ─────────────────────


def test_classify_outcome_improved():
    assert classify_outcome(0.2, 0.6, 0.5, 0.9) == "improved"


def test_classify_outcome_degraded():
    assert classify_outcome(0.4, 0.1, 0.5, 0.9) == "degraded"


def test_classify_outcome_neutral():
    assert classify_outcome(0.6, 0.6, 0.5, 0.9) == "neutral"


# ── Meta: Adaptive Cooldown (additional cases) ───────────────────


def test_cooldown_high_confidence():
    assert compute_adaptive_cooldown(10, 0.95) == 7


def test_cooldown_low_confidence():
    assert compute_adaptive_cooldown(10, 0.1) == 20


def test_cooldown_minimum():
    assert compute_adaptive_cooldown(1, 0.1) >= 1
