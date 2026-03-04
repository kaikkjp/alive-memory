"""Tests for identity (drift, evolution, history) and meta (controller, evaluation) modules."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime

import pytest

from alive_memory.identity.drift import DriftReport, detect_drift
from alive_memory.identity.evolution import EvolutionDecision, apply_decision, evaluate_drift
from alive_memory.identity.history import get_history, get_trait_timeline, summarize_development
from alive_memory.identity.self_model import (
    get_self_model,
    snapshot,
    update_behavioral_summary,
    update_traits,
)
from alive_memory.meta.controller import (
    Experiment,
    MetricTarget,
    classify_outcome,
    compute_adaptive_cooldown,
    request_correction,
    run_meta_controller,
)
from alive_memory.meta.evaluation import (
    detect_side_effects,
    evaluate_experiment,
    evaluate_pending_experiments,
)
from alive_memory.meta.review import (
    ReviewResult,
    review_self_modifications,
    review_trait_stability,
    run_meta_review,
)
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


# ── Mock Providers ───────────────────────────────────────────────


class MockMetricsProvider:
    """Mock MetricsProvider for testing."""

    def __init__(self, metrics: dict[str, float], cycle_count: int = 0):
        self._metrics = metrics
        self._cycle_count = cycle_count

    async def collect_metrics(self) -> dict[str, float]:
        return self._metrics

    async def get_cycle_count(self) -> int:
        return self._cycle_count


class MockDriveProvider:
    """Mock DriveProvider for testing."""

    def __init__(
        self,
        drive_values: dict[str, float],
        category_map: dict[str, list[str]],
    ):
        self._drive_values = drive_values
        self._category_map = category_map

    async def get_drive_values(self) -> dict[str, float]:
        return self._drive_values

    def get_category_drive_map(self) -> dict[str, list[str]]:
        return self._category_map


# ── Meta: Confidence Persistence ─────────────────────────────────


@pytest.mark.asyncio
async def test_confidence_persists_across_evaluations(storage):
    """Save/get round-trip for confidence."""
    await storage.set_confidence("decay_rate", "recall_quality", 0.75)
    result = await storage.get_confidence("decay_rate", "recall_quality")
    assert result == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_confidence_increases_on_improved(storage):
    """Confidence increases by 0.1 when experiment improves, persisted to DB."""
    await storage.set_parameter("consolidation.decay_rate", 0.6, reason="test")

    # Create and save experiment
    await storage.save_experiment({
        "id": "exp-conf-1",
        "param_key": "consolidation.decay_rate",
        "old_value": 0.5,
        "new_value": 0.6,
        "target_metric": "recall_quality",
        "metric_at_change": 0.3,
        "outcome": "pending",
        "confidence": 0.5,
        "side_effects": [],
        "created_at": datetime.now(UTC).isoformat(),
        "cycle_at_creation": 0,
    })

    # Log enough cycles for age-gating
    for i in range(3):
        await storage.log_cycle({"cycle_number": i})

    targets = [MetricTarget(
        name="recall_quality", min_value=0.5, max_value=0.9,
        param_key="consolidation.decay_rate",
    )]
    evaluated = await evaluate_pending_experiments(
        storage, {"recall_quality": 0.6}, targets, min_age_cycles=2,
    )
    assert len(evaluated) == 1
    assert evaluated[0].outcome == "improved"
    assert evaluated[0].confidence == pytest.approx(0.6)

    # Check DB persistence
    db_conf = await storage.get_confidence("consolidation.decay_rate", "recall_quality")
    assert db_conf == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_confidence_decreases_on_degraded(storage):
    """Confidence decreases by 0.2 when experiment degrades, persisted to DB."""
    await storage.set_parameter("consolidation.decay_rate", 0.6, reason="test")

    await storage.save_experiment({
        "id": "exp-conf-2",
        "param_key": "consolidation.decay_rate",
        "old_value": 0.5,
        "new_value": 0.6,
        "target_metric": "recall_quality",
        "metric_at_change": 0.4,
        "outcome": "pending",
        "confidence": 0.5,
        "side_effects": [],
        "created_at": datetime.now(UTC).isoformat(),
        "cycle_at_creation": 0,
    })

    for i in range(3):
        await storage.log_cycle({"cycle_number": i})

    targets = [MetricTarget(
        name="recall_quality", min_value=0.5, max_value=0.9,
        param_key="consolidation.decay_rate",
    )]
    evaluated = await evaluate_pending_experiments(
        storage, {"recall_quality": 0.2}, targets, min_age_cycles=2,
    )
    assert len(evaluated) == 1
    assert evaluated[0].outcome == "degraded"
    assert evaluated[0].confidence == pytest.approx(0.3)

    db_conf = await storage.get_confidence("consolidation.decay_rate", "recall_quality")
    assert db_conf == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_confidence_default_is_half(storage):
    """get_confidence returns 0.5 if no row exists."""
    result = await storage.get_confidence("nonexistent", "nonexistent")
    assert result == 0.5


# ── Meta: Hard Floor Enforcement ─────────────────────────────────


@pytest.mark.asyncio
async def test_hard_floor_clamps_above_max(storage):
    """Param with max_bound=0.8, adjustment tries 0.9 → clamped to 0.8."""
    # Insert param with max_bound
    conn = await storage._get_db()
    await conn.execute(
        """INSERT INTO parameters (key, value, default_value, min_bound, max_bound)
           VALUES ('test.param', 0.75, 0.5, NULL, 0.8)""",
    )
    await conn.commit()

    target = MetricTarget(
        name="metric_a", min_value=0.5, max_value=0.9,
        param_key="test.param", adjustment_step=0.2,
    )
    experiments = await run_meta_controller(
        storage, {"metric_a": 0.3}, [target],
    )
    assert len(experiments) == 1
    assert experiments[0].new_value == pytest.approx(0.8, abs=0.01)


@pytest.mark.asyncio
async def test_hard_floor_clamps_below_min(storage):
    """Param with min_bound=0.2, adjustment tries 0.1 → clamped to 0.2."""
    conn = await storage._get_db()
    await conn.execute(
        """INSERT INTO parameters (key, value, default_value, min_bound, max_bound)
           VALUES ('test.param2', 0.25, 0.5, 0.2, NULL)""",
    )
    await conn.commit()

    target = MetricTarget(
        name="metric_b", min_value=0.3, max_value=0.7,
        param_key="test.param2", adjustment_step=0.2,
    )
    experiments = await run_meta_controller(
        storage, {"metric_b": 0.9}, [target],
    )
    assert len(experiments) == 1
    assert experiments[0].new_value == pytest.approx(0.2, abs=0.01)


@pytest.mark.asyncio
async def test_hard_floor_no_bounds(storage):
    """No bounds set → no clamping beyond soft 0-1."""
    await storage.set_parameter("unbounded.param", 0.5, reason="init")

    target = MetricTarget(
        name="metric_c", min_value=0.5, max_value=0.9,
        param_key="unbounded.param", adjustment_step=0.1,
    )
    experiments = await run_meta_controller(
        storage, {"metric_c": 0.3}, [target],
    )
    assert len(experiments) == 1
    assert experiments[0].new_value == pytest.approx(0.6, abs=0.01)


@pytest.mark.asyncio
async def test_hard_floor_in_request_correction(storage):
    """request_correction also respects hard floor bounds."""
    conn = await storage._get_db()
    await conn.execute(
        """INSERT INTO parameters (key, value, default_value, min_bound, max_bound)
           VALUES ('floor.param', 0.5, 0.5, 0.3, 0.8)""",
    )
    await conn.commit()

    await request_correction(storage, "floor.param", 0.95)
    params = await storage.get_parameters()
    assert params["floor.param"] == pytest.approx(0.8, abs=0.01)

    await request_correction(storage, "floor.param", 0.1)
    params = await storage.get_parameters()
    assert params["floor.param"] == pytest.approx(0.3, abs=0.01)


# ── Meta: Experiment Lifecycle ───────────────────────────────────


@pytest.mark.asyncio
async def test_experiment_persisted_to_storage(storage):
    """run_meta_controller saves experiment to DB."""
    await storage.set_parameter("consolidation.decay_rate", 0.5, reason="init")

    target = MetricTarget(
        name="recall_quality", min_value=0.5, max_value=0.9,
        param_key="consolidation.decay_rate", adjustment_step=0.1,
    )
    experiments = await run_meta_controller(
        storage, {"recall_quality": 0.3}, [target],
    )
    assert len(experiments) == 1

    # Verify it's in the DB
    pending = await storage.get_pending_experiments(min_age_cycles=0)
    assert len(pending) == 1
    assert pending[0]["param_key"] == "consolidation.decay_rate"
    assert pending[0]["outcome"] == "pending"


@pytest.mark.asyncio
async def test_experiment_age_gating(storage):
    """Experiment created at cycle 5, evaluated at cycle 6 with min_age=2 → skipped."""
    await storage.set_parameter("consolidation.decay_rate", 0.5, reason="init")

    # Log 5 cycles first
    for i in range(5):
        await storage.log_cycle({"cycle_number": i})

    target = MetricTarget(
        name="recall_quality", min_value=0.5, max_value=0.9,
        param_key="consolidation.decay_rate", adjustment_step=0.1,
    )
    await run_meta_controller(storage, {"recall_quality": 0.3}, [target])

    # Log 1 more cycle (total 6, experiment at cycle 5, age = 1)
    await storage.log_cycle({"cycle_number": 5})

    targets = [target]
    evaluated = await evaluate_pending_experiments(
        storage, {"recall_quality": 0.6}, targets, min_age_cycles=2,
    )
    assert len(evaluated) == 0  # Not old enough


@pytest.mark.asyncio
async def test_experiment_evaluated_after_min_age(storage):
    """Experiment created at cycle 5, evaluated at cycle 8 with min_age=2 → evaluated."""
    await storage.set_parameter("consolidation.decay_rate", 0.5, reason="init")

    # Log 5 cycles first
    for i in range(5):
        await storage.log_cycle({"cycle_number": i})

    target = MetricTarget(
        name="recall_quality", min_value=0.5, max_value=0.9,
        param_key="consolidation.decay_rate", adjustment_step=0.1,
    )
    await run_meta_controller(storage, {"recall_quality": 0.3}, [target])

    # Log 3 more cycles (total 8, experiment at cycle 5, age = 3 >= 2)
    for i in range(5, 8):
        await storage.log_cycle({"cycle_number": i})

    targets = [target]
    evaluated = await evaluate_pending_experiments(
        storage, {"recall_quality": 0.6}, targets, min_age_cycles=2,
    )
    assert len(evaluated) == 1
    assert evaluated[0].outcome == "improved"


@pytest.mark.asyncio
async def test_experiment_revert_on_degraded(storage):
    """Full lifecycle: create → evaluate(degraded) → param reverted."""
    await storage.set_parameter("consolidation.decay_rate", 0.5, reason="init")

    target = MetricTarget(
        name="recall_quality", min_value=0.5, max_value=0.9,
        param_key="consolidation.decay_rate", adjustment_step=0.1,
    )
    await run_meta_controller(storage, {"recall_quality": 0.3}, [target])

    # Log enough cycles
    for i in range(3):
        await storage.log_cycle({"cycle_number": i})

    targets = [target]
    evaluated = await evaluate_pending_experiments(
        storage, {"recall_quality": 0.2}, targets, min_age_cycles=2,
    )
    assert len(evaluated) == 1
    assert evaluated[0].outcome == "degraded"

    # Param should be reverted to old value
    params = await storage.get_parameters()
    assert params["consolidation.decay_rate"] == pytest.approx(0.5, abs=0.01)


@pytest.mark.asyncio
async def test_experiment_accepted_on_improved(storage):
    """Full lifecycle: create → evaluate(improved) → confidence up."""
    await storage.set_parameter("consolidation.decay_rate", 0.5, reason="init")

    target = MetricTarget(
        name="recall_quality", min_value=0.5, max_value=0.9,
        param_key="consolidation.decay_rate", adjustment_step=0.1,
    )
    await run_meta_controller(storage, {"recall_quality": 0.3}, [target])

    for i in range(3):
        await storage.log_cycle({"cycle_number": i})

    targets = [target]
    evaluated = await evaluate_pending_experiments(
        storage, {"recall_quality": 0.7}, targets, min_age_cycles=2,
    )
    assert len(evaluated) == 1
    assert evaluated[0].outcome == "improved"
    assert evaluated[0].confidence > 0.5

    # Param stays at new value (not reverted)
    params = await storage.get_parameters()
    assert params["consolidation.decay_rate"] == pytest.approx(0.6, abs=0.01)


# ── Meta: MetricsProvider Protocol ───────────────────────────────


@pytest.mark.asyncio
async def test_run_meta_controller_with_provider(storage):
    """Pass MetricsProvider instead of dict."""
    await storage.set_parameter("consolidation.decay_rate", 0.5, reason="init")

    provider = MockMetricsProvider({"recall_quality": 0.3}, cycle_count=5)

    target = MetricTarget(
        name="recall_quality", min_value=0.5, max_value=0.9,
        param_key="consolidation.decay_rate", adjustment_step=0.1,
    )
    experiments = await run_meta_controller(
        storage, targets=[target], metrics_provider=provider,
    )
    assert len(experiments) == 1
    assert experiments[0].new_value == pytest.approx(0.6, abs=0.01)
    assert experiments[0].cycle_at_creation == 5


@pytest.mark.asyncio
async def test_run_meta_controller_metrics_dict_backward_compat(storage):
    """Existing dict path still works."""
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


# ── Meta: Review — Trait Stability ───────────────────────────────


@pytest.mark.asyncio
async def test_review_trait_stability_stable(storage):
    """Consistent small deltas → high score, 'stable'."""
    model = await storage.get_self_model()
    model.drift_history = [
        {"trait": "warmth", "delta": 0.01},
        {"trait": "warmth", "delta": 0.005},
        {"trait": "warmth", "delta": 0.01},
    ]
    await storage.save_self_model(model)

    reports = await review_trait_stability(storage, window=3)
    assert len(reports) == 1
    assert reports[0].trait == "warmth"
    assert reports[0].direction == "stable"
    assert reports[0].stability_score > 0.8


@pytest.mark.asyncio
async def test_review_trait_stability_oscillating(storage):
    """Mixed sign deltas → 'oscillating'."""
    model = await storage.get_self_model()
    model.drift_history = [
        {"trait": "warmth", "delta": 0.2},
        {"trait": "warmth", "delta": -0.2},
        {"trait": "warmth", "delta": 0.2},
    ]
    await storage.save_self_model(model)

    reports = await review_trait_stability(storage, window=3)
    assert len(reports) == 1
    assert reports[0].trait == "warmth"
    assert reports[0].direction == "oscillating"


@pytest.mark.asyncio
async def test_review_trait_stability_directional(storage):
    """Same sign deltas → 'increasing' or 'decreasing'."""
    model = await storage.get_self_model()
    model.drift_history = [
        {"trait": "warmth", "delta": 0.1},
        {"trait": "warmth", "delta": 0.15},
        {"trait": "warmth", "delta": 0.12},
    ]
    await storage.save_self_model(model)

    reports = await review_trait_stability(storage, window=3)
    assert len(reports) == 1
    assert reports[0].trait == "warmth"
    assert reports[0].direction == "increasing"


# ── Meta: Review — Self-Modifications ────────────────────────────


@pytest.mark.asyncio
async def test_review_self_modifications_reverts(storage):
    """Drive degraded → param reverted."""
    await storage.set_parameter("social.engagement", 0.8, reason="test")

    drive_provider = MockDriveProvider(
        drive_values={"social": 0.3, "expression": 0.7},  # social degraded below 0.35
        category_map={"social": ["social", "expression"]},
    )

    reverted = await review_self_modifications(storage, drive_provider)
    assert "social.engagement" in reverted

    # Param should be reverted to default (0.5)
    params = await storage.get_parameters()
    assert params["social.engagement"] == pytest.approx(0.5, abs=0.01)


@pytest.mark.asyncio
async def test_review_self_modifications_no_revert(storage):
    """Drives healthy → nothing reverted."""
    await storage.set_parameter("social.engagement", 0.8, reason="test")

    drive_provider = MockDriveProvider(
        drive_values={"social": 0.6, "expression": 0.7},  # all healthy
        category_map={"social": ["social", "expression"]},
    )

    reverted = await review_self_modifications(storage, drive_provider)
    assert reverted == []


@pytest.mark.asyncio
async def test_run_meta_review_integration(storage):
    """Full review with mock DriveProvider."""
    model = await storage.get_self_model()
    model.drift_history = [
        {"trait": "warmth", "delta": 0.01},
        {"trait": "warmth", "delta": 0.01},
        {"trait": "warmth", "delta": 0.01},
    ]
    await storage.save_self_model(model)

    await storage.set_parameter("social.engagement", 0.8, reason="test")

    drive_provider = MockDriveProvider(
        drive_values={"social": 0.3},
        category_map={"social": ["social"]},
    )

    result = await run_meta_review(
        storage, drive_provider=drive_provider, consistency_window=3,
    )
    assert isinstance(result, ReviewResult)
    assert len(result.stability_reports) == 1
    assert result.stability_reports[0].trait == "warmth"
    assert "social.engagement" in result.reverted_params


# ── Meta: request_correction ─────────────────────────────────────


@pytest.mark.asyncio
async def test_request_correction_sets_param(storage):
    """Sets param and logs reason."""
    await storage.set_parameter("test.param", 0.5, reason="init")

    await request_correction(storage, "test.param", 0.7, reason="identity-correction")

    params = await storage.get_parameters()
    assert params["test.param"] == pytest.approx(0.7, abs=0.01)


@pytest.mark.asyncio
async def test_request_correction_respects_floors(storage):
    """Value clamped to hard floor."""
    conn = await storage._get_db()
    await conn.execute(
        """INSERT INTO parameters (key, value, default_value, min_bound, max_bound)
           VALUES ('bounded.param', 0.5, 0.5, 0.2, 0.8)""",
    )
    await conn.commit()

    await request_correction(storage, "bounded.param", 0.95)
    params = await storage.get_parameters()
    assert params["bounded.param"] == pytest.approx(0.8, abs=0.01)
