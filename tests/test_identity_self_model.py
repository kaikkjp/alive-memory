"""Tests for enhanced identity self-model (TraitConfig, EMA, SelfModelManager)."""

from __future__ import annotations

import os
import tempfile

import pytest

from alive_memory.identity.self_model import (
    SelfModelManager,
    TraitConfig,
    _ema_update,
    get_self_model,
    snapshot,
    update_behavioral_summary,
    update_traits,
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


# ── TraitConfig ──────────────────────────────────────────────────


def test_trait_config_creation():
    tc = TraitConfig(
        trait_names=["bravery", "patience"],
        positive_indicators={
            "bravery": frozenset({"fight", "explore"}),
            "patience": frozenset({"wait", "meditate"}),
        },
        negative_indicators={
            "bravery": frozenset({"flee", "hide"}),
            "patience": frozenset({"rush", "snap"}),
        },
        ema_alpha=0.1,
        bounds=(-1.0, 1.0),
    )
    assert tc.trait_names == ["bravery", "patience"]
    assert "fight" in tc.positive_indicators["bravery"]
    assert tc.ema_alpha == 0.1
    assert tc.bounds == (-1.0, 1.0)


# ── EMA pure function ───────────────────────────────────────────


def test_ema_update_pure_function():
    assert _ema_update(0.5, 1.0, 0.05) == pytest.approx(0.525, abs=0.001)


def test_ema_update_no_change():
    assert _ema_update(0.5, 0.5, 0.05) == pytest.approx(0.5, abs=0.001)


def test_ema_update_full_weight():
    assert _ema_update(0.0, 1.0, 1.0) == pytest.approx(1.0, abs=0.001)


# ── SelfModelManager.update_from_actions ─────────────────────────


@pytest.mark.asyncio
async def test_update_from_actions(storage):
    tc = TraitConfig(
        trait_names=["bravery"],
        positive_indicators={"bravery": frozenset({"fight", "explore"})},
        negative_indicators={"bravery": frozenset({"flee"})},
        ema_alpha=0.1,
        bounds=(0.0, 1.0),
        initial_values={"bravery": 0.5},
    )
    mgr = SelfModelManager(storage, config=tc)

    # All positive actions → signal should push toward high end
    model = await mgr.update_from_actions(["fight", "explore", "fight"])
    assert model.traits["bravery"] > 0.5
    assert model.version == 1


@pytest.mark.asyncio
async def test_update_from_actions_no_config(storage):
    mgr = SelfModelManager(storage, config=None)
    model = await mgr.update_from_actions(["fight", "explore"])
    # No-op: no trait config → returns model unchanged
    assert model.traits == {}


@pytest.mark.asyncio
async def test_update_from_actions_empty_actions(storage):
    tc = TraitConfig(
        trait_names=["bravery"],
        positive_indicators={"bravery": frozenset({"fight"})},
        negative_indicators={"bravery": frozenset({"flee"})},
        ema_alpha=0.1,
        bounds=(0.0, 1.0),
    )
    mgr = SelfModelManager(storage, config=tc)
    model = await mgr.update_from_actions([])
    assert model.traits == {}  # No actions → no initialization


# ── Trait bounds configurable ────────────────────────────────────


@pytest.mark.asyncio
async def test_trait_bounds_configurable(storage):
    tc = TraitConfig(
        trait_names=["mood"],
        positive_indicators={"mood": frozenset({"laugh"})},
        negative_indicators={"mood": frozenset({"cry"})},
        ema_alpha=0.5,
        bounds=(-1.0, 1.0),
        initial_values={"mood": 0.0},
    )
    mgr = SelfModelManager(storage, config=tc)

    # All positive → should move toward +1
    model = await mgr.update_from_actions(["laugh"])
    assert -1.0 <= model.traits["mood"] <= 1.0
    assert model.traits["mood"] > 0.0


@pytest.mark.asyncio
async def test_trait_bounds_zero_to_one(storage):
    tc = TraitConfig(
        trait_names=["energy"],
        positive_indicators={"energy": frozenset({"eat"})},
        negative_indicators={"energy": frozenset({"run"})},
        ema_alpha=0.5,
        bounds=(0.0, 1.0),
        initial_values={"energy": 0.5},
    )
    mgr = SelfModelManager(storage, config=tc)

    # All negative → should move toward 0
    model = await mgr.update_from_actions(["run", "run", "run"])
    assert 0.0 <= model.traits["energy"] <= 1.0
    assert model.traits["energy"] < 0.5


# ── Behavioral signature ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_behavioral_signature_update(storage):
    mgr = SelfModelManager(storage)
    model = await mgr.update_behavioral_signature({
        "action_freq": {"greet": 0.5, "trade": 0.3},
        "avg_response_length": 42,
    })
    assert model.behavioral_signature["action_freq"] == {"greet": 0.5, "trade": 0.3}
    assert model.behavioral_signature["avg_response_length"] == 42

    # Verify persistence
    model2 = await mgr.get()
    assert model2.behavioral_signature["avg_response_length"] == 42


# ── Relational stance ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_relational_stance_update(storage):
    mgr = SelfModelManager(storage)
    model = await mgr.update_relational_stance({
        "warmth": 0.7,
        "guardedness": 0.3,
    })
    assert model.relational_stance["warmth"] == 0.7
    assert model.relational_stance["guardedness"] == 0.3

    # Verify persistence
    model2 = await mgr.get()
    assert model2.relational_stance["warmth"] == 0.7


# ── Narrative management ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_needs_narrative_regen_true(storage):
    mgr = SelfModelManager(storage)

    # Set narrative with trait snapshot
    await mgr.update_traits({"warmth": 0.5})
    await mgr.update_narrative("I am a warm character.")

    # Now shift trait significantly
    model = await mgr.update_traits({"warmth": 0.8})
    assert mgr.needs_narrative_regen(model, threshold=0.2)


@pytest.mark.asyncio
async def test_needs_narrative_regen_false(storage):
    mgr = SelfModelManager(storage)

    await mgr.update_traits({"warmth": 0.5})
    await mgr.update_narrative("I am a warm character.")

    # Small shift — below threshold
    model = await mgr.update_traits({"warmth": 0.55})
    assert not mgr.needs_narrative_regen(model, threshold=0.2)


@pytest.mark.asyncio
async def test_self_narrative_update(storage):
    mgr = SelfModelManager(storage)

    model = await mgr.update_narrative("First narrative")
    assert model.self_narrative == "First narrative"
    assert model.narrative_version == 1

    model2 = await mgr.update_narrative("Second narrative")
    assert model2.self_narrative == "Second narrative"
    assert model2.narrative_version == 2


# ── Backward compatibility ───────────────────────────────────────


@pytest.mark.asyncio
async def test_backward_compat_get_self_model(storage):
    model = await get_self_model(storage)
    assert model.version == 0
    assert model.traits == {}


@pytest.mark.asyncio
async def test_backward_compat_update_traits(storage):
    model = await update_traits(storage, {"warmth": 0.7, "curiosity": 0.6})
    assert model.traits["warmth"] == 0.7
    assert model.traits["curiosity"] == 0.6
    assert model.version == 1


@pytest.mark.asyncio
async def test_backward_compat_update_traits_clamps(storage):
    model = await update_traits(storage, {"extreme": 5.0})
    assert model.traits["extreme"] == 1.0

    model = await update_traits(storage, {"extreme": -5.0})
    assert model.traits["extreme"] == -1.0


@pytest.mark.asyncio
async def test_backward_compat_update_behavioral_summary(storage):
    model = await update_behavioral_summary(storage, "I am warm and curious.")
    assert model.behavioral_summary == "I am warm and curious."
    assert model.version == 1


@pytest.mark.asyncio
async def test_backward_compat_snapshot(storage):
    model = await snapshot(storage)
    assert model.snapshot_at is not None
