"""Tests for enhanced identity evolution (GuardRailConfig, IdentityEvolution)."""

from __future__ import annotations

import os
import tempfile

import pytest

from alive_memory.identity.drift import DriftReport
from alive_memory.identity.evolution import (
    EvolutionAction,
    EvolutionDecision,
    GuardRailConfig,
    IdentityEvolution,
    apply_decision,
    evaluate_drift,
)
from alive_memory.identity.self_model import update_traits
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


def _make_report(
    *,
    trait="warmth",
    direction="increase",
    magnitude=0.3,
    old_value=0.5,
    new_value=0.8,
    confidence=0.9,
    window_cycles=5,
) -> DriftReport:
    return DriftReport(
        trait=trait,
        direction=direction,
        magnitude=magnitude,
        old_value=old_value,
        new_value=new_value,
        confidence=confidence,
        window_cycles=window_cycles,
    )


# ── Guard Rails ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_guard_rail_correction_below_min(storage):
    gr = GuardRailConfig(protected_traits={"warmth": (0.3, 0.9)})
    evo = IdentityEvolution(storage, guard_rails=gr)

    report = _make_report(new_value=0.1, direction="decrease")
    decision = await evo.evaluate(report)
    assert decision.action == "correct"
    assert decision.correction_value == 0.3


@pytest.mark.asyncio
async def test_guard_rail_correction_above_max(storage):
    gr = GuardRailConfig(protected_traits={"warmth": (0.3, 0.9)})
    evo = IdentityEvolution(storage, guard_rails=gr)

    report = _make_report(new_value=0.95)
    decision = await evo.evaluate(report)
    assert decision.action == "correct"
    assert decision.correction_value == 0.9


@pytest.mark.asyncio
async def test_guard_rail_within_bounds(storage):
    gr = GuardRailConfig(protected_traits={"warmth": (0.3, 0.9)})
    evo = IdentityEvolution(storage, guard_rails=gr)

    report = _make_report(new_value=0.7, confidence=0.9, window_cycles=5)
    decision = await evo.evaluate(report)
    # Within bounds → not corrected at step 1
    assert decision.action != "correct" or decision.correction_value is None


# ── Sustained Drift ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sustained_drift_accept(storage):
    gr = GuardRailConfig(min_sustained_cycles=3)
    evo = IdentityEvolution(storage, guard_rails=gr)

    report = _make_report(confidence=0.9, magnitude=0.3, window_cycles=5)
    decision = await evo.evaluate(report)
    assert decision.action == "accept"
    assert decision.sustained_cycles == 5


@pytest.mark.asyncio
async def test_sustained_drift_too_few_cycles(storage):
    gr = GuardRailConfig(min_sustained_cycles=10)
    evo = IdentityEvolution(storage, guard_rails=gr)

    # Only 5 cycles but min is 10 → falls through step 2
    # confidence=0.9 > 0.7 so it won't hit correction provider
    # Goes to step 4: confidence >= 0.4 and magnitude > 0.2 → ACCEPT at baseline shift
    report = _make_report(confidence=0.9, magnitude=0.3, window_cycles=5)
    decision = await evo.evaluate(report)
    # Falls through to step 4 baseline shift
    assert decision.action == "accept"
    assert "magnitude significant" in decision.reason.lower() or "moderate" in decision.reason.lower()


# ── Correction Provider ──────────────────────────────────────────


class AcceptingProvider:
    async def request_correction(self, trait: str, target: float, reason: str) -> bool:
        return True


class RejectingProvider:
    async def request_correction(self, trait: str, target: float, reason: str) -> bool:
        return False


@pytest.mark.asyncio
async def test_correction_provider_accepts(storage):
    evo = IdentityEvolution(
        storage,
        correction_provider=AcceptingProvider(),
    )
    # Moderate confidence (0.4 < 0.5 < 0.7) triggers provider
    report = _make_report(confidence=0.5, magnitude=0.2)
    decision = await evo.evaluate(report)
    assert decision.action == "correct"


@pytest.mark.asyncio
async def test_correction_provider_rejects(storage):
    evo = IdentityEvolution(
        storage,
        correction_provider=RejectingProvider(),
    )
    report = _make_report(confidence=0.5, magnitude=0.2)
    decision = await evo.evaluate(report)
    assert decision.action == "defer"


@pytest.mark.asyncio
async def test_no_correction_provider_skips(storage):
    evo = IdentityEvolution(storage)
    # Moderate confidence → no provider → goes to step 4
    report = _make_report(confidence=0.5, magnitude=0.3)
    decision = await evo.evaluate(report)
    # Step 4: confidence >= 0.4 and magnitude > 0.2 → ACCEPT
    assert decision.action == "accept"


# ── Max Updates Per Sleep ────────────────────────────────────────


@pytest.mark.asyncio
async def test_max_updates_per_sleep_limit(storage):
    gr = GuardRailConfig(max_updates_per_sleep=2)
    evo = IdentityEvolution(storage, guard_rails=gr)

    # Use up the limit with apply calls
    for _ in range(2):
        d = EvolutionDecision(action="accept", trait="warmth", reason="test")
        await evo.apply(d)

    # Now evaluate — should defer due to update limit
    report = _make_report(confidence=0.5, magnitude=0.3)
    decision = await evo.evaluate(report)
    assert decision.action == "defer"
    assert "limit" in decision.reason.lower()


@pytest.mark.asyncio
async def test_reset_sleep_counter(storage):
    gr = GuardRailConfig(max_updates_per_sleep=1)
    evo = IdentityEvolution(storage, guard_rails=gr)

    d = EvolutionDecision(action="accept", trait="warmth", reason="test")
    await evo.apply(d)

    evo.reset_sleep_counter()

    report = _make_report(confidence=0.5, magnitude=0.3)
    decision = await evo.evaluate(report)
    assert decision.action != "defer" or "limit" not in decision.reason.lower()


# ── Baseline Shift ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_baseline_shift_accept(storage):
    evo = IdentityEvolution(storage)
    report = _make_report(confidence=0.5, magnitude=0.3)
    decision = await evo.evaluate(report)
    assert decision.action == "accept"


@pytest.mark.asyncio
async def test_baseline_shift_defer(storage):
    evo = IdentityEvolution(storage)
    report = _make_report(confidence=0.3, magnitude=0.1)
    decision = await evo.evaluate(report)
    assert decision.action == "defer"


# ── Apply Decision ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_correct_updates_trait(storage):
    await update_traits(storage, {"warmth": 0.1})
    evo = IdentityEvolution(storage)

    decision = EvolutionDecision(
        action="correct", trait="warmth",
        reason="Too low", correction_value=0.5,
    )
    await evo.apply(decision)

    model = await storage.get_self_model()
    assert model.traits["warmth"] == pytest.approx(0.5, abs=0.01)


@pytest.mark.asyncio
async def test_apply_accept_noop(storage):
    await update_traits(storage, {"warmth": 0.8})
    evo = IdentityEvolution(storage)

    decision = EvolutionDecision(
        action="accept", trait="warmth", reason="Natural growth",
    )
    await evo.apply(decision)

    model = await storage.get_self_model()
    assert model.traits["warmth"] == pytest.approx(0.8, abs=0.01)


@pytest.mark.asyncio
async def test_apply_defer_noop(storage):
    await update_traits(storage, {"warmth": 0.8})
    evo = IdentityEvolution(storage)

    decision = EvolutionDecision(
        action="defer", trait="warmth", reason="Needs review",
    )
    await evo.apply(decision)

    model = await storage.get_self_model()
    assert model.traits["warmth"] == pytest.approx(0.8, abs=0.01)


# ── Event Hook ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_event_hook_called(storage):
    decisions_received: list[EvolutionDecision] = []

    async def hook(d: EvolutionDecision) -> None:
        decisions_received.append(d)

    evo = IdentityEvolution(storage, on_decision=hook)
    decision = EvolutionDecision(
        action="accept", trait="warmth", reason="test",
    )
    await evo.apply(decision)
    assert len(decisions_received) == 1
    assert decisions_received[0].trait == "warmth"


# ── Evolution Decision Logged ────────────────────────────────────


@pytest.mark.asyncio
async def test_evolution_decision_logged(storage):
    evo = IdentityEvolution(storage)
    decision = EvolutionDecision(
        action="accept", trait="warmth", reason="logged test",
    )
    await evo.apply(decision)

    # Verify it was written to evolution_log
    conn = await storage._get_db()
    cursor = await conn.execute("SELECT * FROM evolution_log")
    rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0]["action"] == "accept"
    assert rows[0]["trait"] == "warmth"


# ── Backward Compatibility ───────────────────────────────────────


@pytest.mark.asyncio
async def test_backward_compat_evaluate_drift(storage):
    report = _make_report(confidence=0.9, magnitude=0.3)
    decision = await evaluate_drift(report, storage)
    assert decision.action == "accept"


@pytest.mark.asyncio
async def test_backward_compat_evaluate_drift_protected(storage):
    report = _make_report(new_value=0.1, direction="decrease")
    protected = {"warmth": (0.3, 0.9)}
    decision = await evaluate_drift(report, storage, protected_traits=protected)
    assert decision.action == "correct"
    assert decision.correction_value == 0.3


@pytest.mark.asyncio
async def test_backward_compat_apply_decision(storage):
    await update_traits(storage, {"warmth": 0.1})
    decision = EvolutionDecision(
        action="correct", trait="warmth",
        reason="Too low", correction_value=0.5,
    )
    await apply_decision(decision, storage)

    model = await storage.get_self_model()
    assert model.traits["warmth"] == pytest.approx(0.5, abs=0.01)


# ── EvolutionAction Enum ─────────────────────────────────────────


def test_evolution_action_values():
    assert EvolutionAction.ACCEPT.value == "accept"
    assert EvolutionAction.CORRECT.value == "correct"
    assert EvolutionAction.DEFER.value == "defer"
