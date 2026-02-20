"""Tests for sim.runner — SimulationRunner end-to-end."""

import pytest
import pytest_asyncio

from sim.runner import SimulationRunner, CycleResult, SimulationResult


@pytest.mark.asyncio
async def test_basic_run_completes():
    """Runner should complete a short mock run without errors."""
    runner = SimulationRunner(
        variant="full",
        scenario="standard",
        num_cycles=50,
        llm_mode="mock",
        seed=42,
    )
    result = await runner.run()

    assert isinstance(result, SimulationResult)
    assert len(result.cycles) == 50
    assert result.variant == "full"
    assert result.scenario == "standard"


@pytest.mark.asyncio
async def test_deterministic_with_same_seed():
    """Same seed should produce identical results."""
    async def run_once(seed):
        runner = SimulationRunner(
            variant="full", scenario="standard",
            num_cycles=20, llm_mode="mock", seed=seed,
        )
        return await runner.run()

    r1 = await run_once(42)
    r2 = await run_once(42)

    # Same cycle types
    for c1, c2 in zip(r1.cycles, r2.cycles):
        assert c1.cycle_type == c2.cycle_type
        assert c1.action == c2.action


@pytest.mark.asyncio
async def test_different_seeds_differ():
    """Different seeds should produce different results."""
    async def run_once(seed):
        runner = SimulationRunner(
            variant="full", scenario="standard",
            num_cycles=50, llm_mode="mock", seed=seed,
        )
        return await runner.run()

    r1 = await run_once(42)
    r2 = await run_once(99)

    # At least some cycles should differ
    differences = sum(
        1 for c1, c2 in zip(r1.cycles, r2.cycles)
        if c1.cycle_type != c2.cycle_type
    )
    assert differences > 0


@pytest.mark.asyncio
async def test_visitor_events_create_dialogue():
    """Visitor events should trigger dialogue cycles."""
    runner = SimulationRunner(
        variant="full",
        scenario="standard",
        num_cycles=150,  # includes first visitor at cycle 100
        llm_mode="mock",
        seed=42,
    )
    result = await runner.run()

    # Should have some dialogues
    assert result.total_dialogues > 0


@pytest.mark.asyncio
async def test_sleep_cycles():
    """Sleep windows should produce sleep cycles."""
    # Start at 2AM JST — should hit sleep window at 3AM
    runner = SimulationRunner(
        variant="full",
        scenario="isolation",
        num_cycles=100,
        llm_mode="mock",
        seed=42,
        start_time="2026-02-01T02:00:00+09:00",
    )
    result = await runner.run()

    assert len(result.sleep_cycles) > 0


@pytest.mark.asyncio
async def test_block_sleep():
    """block_sleep=True should prevent sleep cycles."""
    runner = SimulationRunner(
        variant="full",
        scenario="isolation",
        num_cycles=100,
        llm_mode="mock",
        seed=42,
        start_time="2026-02-01T02:00:00+09:00",
        block_sleep=True,
    )
    result = await runner.run()

    assert len(result.sleep_cycles) == 0


@pytest.mark.asyncio
async def test_stateless_baseline():
    """Stateless baseline should run without errors."""
    runner = SimulationRunner(
        variant="stateless",
        scenario="standard",
        num_cycles=50,
        llm_mode="mock",
        seed=42,
    )
    result = await runner.run()

    assert len(result.cycles) == 50
    assert result.variant == "stateless"
    # Stateless never sleeps
    assert len(result.sleep_cycles) == 0


@pytest.mark.asyncio
async def test_react_baseline():
    """ReAct baseline should run without errors."""
    runner = SimulationRunner(
        variant="react",
        scenario="standard",
        num_cycles=50,
        llm_mode="mock",
        seed=42,
    )
    result = await runner.run()

    assert len(result.cycles) == 50
    assert result.variant == "react"


@pytest.mark.asyncio
async def test_ablation_no_drives():
    """no_drives ablation should keep flat drives."""
    runner = SimulationRunner(
        variant="no_drives",
        scenario="standard",
        num_cycles=50,
        llm_mode="mock",
        seed=42,
    )
    result = await runner.run()

    assert len(result.cycles) == 50
    # Drives should remain flat
    for cycle in result.cycles:
        if cycle.drives:
            assert cycle.drives["social_hunger"] == 0.5
            assert cycle.drives["curiosity"] == 0.5


@pytest.mark.asyncio
async def test_ablation_no_sleep():
    """no_sleep ablation should never sleep."""
    runner = SimulationRunner(
        variant="no_sleep",
        scenario="isolation",
        num_cycles=100,
        llm_mode="mock",
        seed=42,
        start_time="2026-02-01T02:00:00+09:00",
    )
    result = await runner.run()

    assert len(result.sleep_cycles) == 0


@pytest.mark.asyncio
async def test_ablation_no_affect():
    """no_affect ablation should keep neutral mood."""
    runner = SimulationRunner(
        variant="no_affect",
        scenario="standard",
        num_cycles=50,
        llm_mode="mock",
        seed=42,
    )
    result = await runner.run()

    for cycle in result.cycles:
        if cycle.drives:
            assert cycle.drives["mood_valence"] == 0.0
            assert cycle.drives["mood_arousal"] == 0.3


@pytest.mark.asyncio
async def test_death_spiral_scenario():
    """Death spiral should start with negative drives."""
    runner = SimulationRunner(
        variant="full",
        scenario="death_spiral",
        num_cycles=50,
        llm_mode="mock",
        seed=42,
    )
    result = await runner.run()

    # First cycle should have negative valence from set_drives
    assert result.cycles[0].drives["mood_valence"] < 0


@pytest.mark.asyncio
async def test_visitor_flood_scenario():
    """Visitor flood should produce many dialogue cycles."""
    runner = SimulationRunner(
        variant="full",
        scenario="visitor_flood",
        num_cycles=100,
        llm_mode="mock",
        seed=42,
    )
    result = await runner.run()

    assert result.total_dialogues > 0
    assert len(result.visitors) > 0


@pytest.mark.asyncio
async def test_export(tmp_path):
    """Export should write a JSON file."""
    runner = SimulationRunner(
        variant="full",
        scenario="standard",
        num_cycles=20,
        llm_mode="mock",
        seed=42,
        output_dir=str(tmp_path),
    )
    result = await runner.run()
    output_path = await runner.export(result)

    assert output_path.exists()
    assert output_path.suffix == ".json"


@pytest.mark.asyncio
async def test_to_dict():
    """SimulationResult.to_dict should produce serializable dict."""
    runner = SimulationRunner(
        variant="full",
        scenario="standard",
        num_cycles=20,
        llm_mode="mock",
        seed=42,
    )
    result = await runner.run()
    d = result.to_dict()

    assert d["variant"] == "full"
    assert d["scenario"] == "standard"
    assert d["num_cycles"] == 20
    assert len(d["cycles"]) == 20
    assert "drives_history" in d


@pytest.mark.asyncio
async def test_ablation_no_memory_strips_updates():
    """no_memory ablation should strip memory_updates from cycle output."""
    runner = SimulationRunner(
        variant="no_memory", scenario="visitor_flood",
        num_cycles=100, llm_mode="mock", seed=42,
    )
    result = await runner.run()

    # no_memory should have empty memory_updates on every cycle
    for cycle in result.cycles:
        assert cycle.memory_updates == [], (
            f"cycle {cycle.cycle_num} has memory_updates: {cycle.memory_updates}"
        )

    # Verify the ablation transform is wired: run with full variant and
    # inject a fake memory_update via the pipeline to confirm full mode
    # would preserve it. We test the transform directly instead.
    from sim.runner import SimulationRunner as SR
    full_runner = SR(variant="full", scenario="standard", num_cycles=1, llm_mode="mock", seed=42)
    mem_runner = SR(variant="no_memory", scenario="standard", num_cycles=1, llm_mode="mock", seed=42)

    test_parsed = {"memory_updates": [{"type": "test", "content": {}}], "intentions": []}
    full_result = full_runner._apply_ablation_transforms(dict(test_parsed))
    mem_result = mem_runner._apply_ablation_transforms(dict(test_parsed))

    assert full_result["memory_updates"] == [{"type": "test", "content": {}}]
    assert mem_result["memory_updates"] == []


@pytest.mark.asyncio
async def test_ablation_no_basal_ganglia_forces_impulse():
    """no_basal_ganglia ablation should force all impulses to 1.0."""
    runner = SimulationRunner(
        variant="no_basal_ganglia", scenario="standard",
        num_cycles=100, llm_mode="mock", seed=42,
    )
    result = await runner.run()

    for cycle in result.cycles:
        for intent in cycle.intentions:
            assert intent["impulse"] == 1.0, (
                f"cycle {cycle.cycle_num} intent has impulse "
                f"{intent['impulse']}, expected 1.0"
            )


@pytest.mark.asyncio
async def test_ablation_no_basal_ganglia_diverges():
    """no_basal_ganglia should produce more journals than full variant.

    Journal intentions have impulse=0.4, which is below the gating
    threshold (0.5). Full pipeline filters them out; the ablation
    forces impulse=1.0 so they pass through.
    """
    full = await SimulationRunner(
        variant="full", scenario="standard",
        num_cycles=300, llm_mode="mock", seed=42,
    ).run()
    ablated = await SimulationRunner(
        variant="no_basal_ganglia", scenario="standard",
        num_cycles=300, llm_mode="mock", seed=42,
    ).run()

    assert ablated.total_journals > full.total_journals, (
        f"Expected no_basal_ganglia to have more journals than full, "
        f"got {ablated.total_journals} vs {full.total_journals}"
    )


@pytest.mark.asyncio
async def test_impulse_gating_handles_string_and_null():
    """Impulse gating should coerce string/null impulses without crashing."""
    runner = SimulationRunner(
        variant="full", scenario="standard",
        num_cycles=1, llm_mode="mock", seed=42,
    )
    # Simulate LLM returning non-numeric impulse values
    parsed = {
        "intentions": [
            {"action": "read_content", "impulse": "0.9"},   # string
            {"action": "write_journal", "impulse": None},    # null
            {"action": "post_x", "impulse": 0.7},           # normal
        ],
        "memory_updates": [],
    }
    transformed = runner._apply_ablation_transforms(parsed)

    # Apply the same gating logic the runner uses
    IMPULSE_THRESHOLD = 0.5
    def _impulse(intent):
        val = intent.get("impulse", 0)
        try:
            return float(val)
        except (TypeError, ValueError):
            return 0.0

    gated = [i for i in transformed["intentions"] if _impulse(i) >= IMPULSE_THRESHOLD]

    # String "0.9" -> 0.9 passes, None -> 0.0 fails, 0.7 passes
    actions = [i["action"] for i in gated]
    assert "read_content" in actions
    assert "post_x" in actions
    assert "write_journal" not in actions


@pytest.mark.asyncio
async def test_sleep_deprivation_blocks_sleep():
    """sleep_deprivation scenario should prevent all sleep cycles."""
    runner = SimulationRunner(
        variant="full", scenario="sleep_deprivation",
        num_cycles=200, llm_mode="mock", seed=42,
        start_time="2026-02-01T02:00:00+09:00",  # start in sleep window
    )
    result = await runner.run()

    assert len(result.sleep_cycles) == 0, (
        f"sleep_deprivation should block all sleep, got {len(result.sleep_cycles)} cycles"
    )


@pytest.mark.asyncio
async def test_unknown_variant_raises():
    """Unknown variant should raise ValueError."""
    with pytest.raises(ValueError, match="Unknown variant"):
        SimulationRunner(variant="quantum")


@pytest.mark.asyncio
async def test_unknown_llm_raises():
    """Unknown LLM mode should raise ValueError."""
    with pytest.raises(ValueError, match="Unknown LLM mode"):
        SimulationRunner(llm_mode="gpt4")
