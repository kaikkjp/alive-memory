"""Tests for the autotune package."""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from alive_memory.autotune.evaluator import (
    aggregate_scores,
    score_recall,
    score_simulation,
)
from alive_memory.autotune.mutator import (
    TUNABLE_PARAMS,
    MutationStrategy,
    mutate,
    select_strategy,
)
from alive_memory.autotune.profiles import PROFILES
from alive_memory.autotune.report import generate_report
from alive_memory.autotune.scenarios.loader import load_scenarios
from alive_memory.autotune.types import (
    AutotuneConfig,
    AutotuneResult,
    ExpectedRecall,
    ExperimentRecord,
    MemoryScore,
    RecallResult,
    SimulationResult,
)
from alive_memory.clock import SimulatedClock, SystemClock
from alive_memory.config import AliveConfig

# ── Clock Tests ──────────────────────────────────────────────────


class TestClock:
    def test_system_clock_returns_utc(self):
        clock = SystemClock()
        now = clock.now()
        assert now.tzinfo is not None

    def test_simulated_clock_advance(self):
        start = datetime(2026, 3, 1, 10, 0, 0, tzinfo=UTC)
        clock = SimulatedClock(start)
        assert clock.now() == start

        clock.advance(3600)  # 1 hour
        assert clock.now().hour == 11

    def test_simulated_clock_set(self):
        clock = SimulatedClock()
        target = datetime(2030, 1, 1, 0, 0, 0, tzinfo=UTC)
        clock.set(target)
        assert clock.now() == target

    def test_simulated_clock_is_clock_protocol(self):
        from alive_memory.clock import Clock
        clock = SimulatedClock()
        assert isinstance(clock, Clock)


# ── Config Promotion Tests ───────────────────────────────────────


class TestConfigPromotion:
    def test_new_intake_keys_have_defaults(self):
        cfg = AliveConfig()
        assert cfg.get("intake.max_day_moments") == 30
        assert cfg.get("intake.salience_threshold") == 0.35
        assert cfg.get("intake.max_salience_threshold") == 0.55
        assert cfg.get("intake.dedup_window_minutes") == 30
        assert cfg.get("intake.dedup_similarity") == 0.85

    def test_config_override(self):
        cfg = AliveConfig({"intake": {"max_day_moments": 50}})
        assert cfg.get("intake.max_day_moments") == 50
        # Other defaults preserved
        assert cfg.get("intake.salience_threshold") == 0.35


# ── Scenario Tests ───────────────────────────────────────────────


class TestScenarios:
    def test_load_builtin_scenarios(self):
        scenarios = load_scenarios("builtin")
        assert len(scenarios) >= 6
        names = {s.name for s in scenarios}
        assert "short_term_recall" in names
        assert "cross_session_recall" in names
        assert "deduplication" in names

    def test_scenario_structure(self):
        scenarios = load_scenarios("builtin")
        for s in scenarios:
            assert s.name
            assert s.description
            assert s.category
            assert len(s.turns) > 0

    def test_recall_turns_have_expected(self):
        scenarios = load_scenarios("builtin")
        for s in scenarios:
            for turn in s.turns:
                if turn.action == "recall":
                    assert turn.expected_recall is not None, (
                        f"Recall turn in {s.name} missing expected_recall"
                    )

    def test_load_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            load_scenarios("/nonexistent/path")


# ── Evaluator Tests ──────────────────────────────────────────────


class TestEvaluator:
    def test_score_recall_perfect(self):
        result = RecallResult(
            turn_index=0,
            query="test",
            recalled_text="I love Rust programming",
            expected=ExpectedRecall(must_contain=["Rust"]),
            num_results=1,
        )
        precision, completeness = score_recall(result)
        assert precision == 1.0
        assert completeness == 1.0

    def test_score_recall_missing(self):
        result = RecallResult(
            turn_index=0,
            query="test",
            recalled_text="I love Python programming",
            expected=ExpectedRecall(must_contain=["Rust", "Go"]),
            num_results=1,
        )
        precision, completeness = score_recall(result)
        assert precision == 1.0
        assert completeness == 0.0

    def test_score_recall_partial(self):
        result = RecallResult(
            turn_index=0,
            query="test",
            recalled_text="I use Rust and Python",
            expected=ExpectedRecall(must_contain=["Rust", "Go"]),
            num_results=1,
        )
        _, completeness = score_recall(result)
        assert completeness == 0.5

    def test_score_recall_must_not_contain(self):
        result = RecallResult(
            turn_index=0,
            query="test",
            recalled_text="I live in Tokyo now",
            expected=ExpectedRecall(
                must_contain=["Tokyo"],
                must_not_contain=["San Francisco"],
            ),
            num_results=1,
        )
        precision, completeness = score_recall(result)
        assert precision == 1.0
        assert completeness == 1.0

    def test_score_recall_min_results_not_met(self):
        result = RecallResult(
            turn_index=0,
            query="test",
            recalled_text="I love Rust",
            expected=ExpectedRecall(must_contain=["Rust"], min_results=3),
            num_results=0,
        )
        precision, completeness = score_recall(result)
        assert precision == 0.0
        assert completeness == 0.0

    def test_score_simulation(self):
        sim_result = SimulationResult(
            scenario_name="test",
            recall_results=[
                RecallResult(
                    turn_index=0,
                    query="q",
                    recalled_text="found keyword",
                    expected=ExpectedRecall(must_contain=["keyword"]),
                    num_results=1,
                    elapsed_ms=10,
                ),
            ],
            moments_recorded=3,
            moments_rejected=1,
        )
        score = score_simulation(sim_result)
        assert score.recall_completeness == 1.0
        assert score.recall_precision == 1.0
        assert score.intake_acceptance_rate == 0.75

    def test_memory_score_composite(self):
        score = MemoryScore(
            recall_precision=1.0,
            recall_completeness=1.0,
            intake_acceptance_rate=1.0,
            dedup_accuracy=1.0,
            decay_accuracy=1.0,
        )
        # Perfect scores → composite near 0
        assert score.composite < 0.1

    def test_aggregate_scores(self):
        scores = {
            "a": MemoryScore(recall_precision=1.0, recall_completeness=1.0),
            "b": MemoryScore(recall_precision=0.0, recall_completeness=0.0),
        }
        agg = aggregate_scores(scores)
        assert 0.0 < agg < 1.0


# ── Mutator Tests ────────────────────────────────────────────────


class TestMutator:
    def test_tunable_params_exist(self):
        assert len(TUNABLE_PARAMS) >= 20

    def test_single_perturbation(self):
        cfg = AliveConfig()
        rng = random.Random(42)
        new_cfg, diff = mutate(cfg, MutationStrategy.SINGLE_PERTURBATION, rng)
        assert len(diff) == 1
        key = list(diff.keys())[0]
        assert "." in key  # dot-notation key

    def test_profile_swap(self):
        cfg = AliveConfig()
        rng = random.Random(42)
        new_cfg, diff = mutate(
            cfg, MutationStrategy.PROFILE_SWAP, rng, iteration=1
        )
        # Profile "high_recall" is index 1
        assert len(diff) >= 1

    def test_correlated_pair(self):
        cfg = AliveConfig()
        rng = random.Random(42)
        new_cfg, diff = mutate(cfg, MutationStrategy.CORRELATED_PAIR, rng)
        assert len(diff) == 2

    def test_values_within_bounds(self):
        cfg = AliveConfig()
        rng = random.Random(42)
        for _ in range(50):
            new_cfg, diff = mutate(cfg, MutationStrategy.SINGLE_PERTURBATION, rng)
            for key, val in diff.items():
                param = next((p for p in TUNABLE_PARAMS if p.key == key), None)
                if param:
                    assert param.min_value <= val <= param.max_value, (
                        f"{key}={val} out of bounds [{param.min_value}, {param.max_value}]"
                    )

    def test_select_strategy_initial(self):
        strategy = select_strategy(0, [])
        assert strategy == MutationStrategy.PROFILE_SWAP

    def test_select_strategy_after_profiles(self):
        strategy = select_strategy(10, [])
        assert strategy == MutationStrategy.SINGLE_PERTURBATION


# ── Profiles Tests ───────────────────────────────────────────────


class TestProfiles:
    def test_profiles_exist(self):
        assert "default" in PROFILES
        assert "high_recall" in PROFILES
        assert "low_noise" in PROFILES

    def test_profile_keys_are_valid(self):
        valid_keys = {p.key for p in TUNABLE_PARAMS}
        for name, profile in PROFILES.items():
            for key in profile:
                assert key in valid_keys, f"Profile {name} has invalid key: {key}"


# ── Report Tests ─────────────────────────────────────────────────


class TestReport:
    def test_generate_report(self):
        result = AutotuneResult(
            best_config={"intake": {"base_salience": 0.4}},
            baseline_composite=0.5,
            best_composite=0.3,
            improvement_pct=40.0,
            experiments=[
                ExperimentRecord(
                    iteration=0,
                    config_snapshot={},
                    config_diff={"intake.base_salience": 0.4},
                    strategy="single_perturbation",
                    composite=0.3,
                    is_best=True,
                    elapsed_seconds=1.0,
                    timestamp="2026-03-01T00:00:00Z",
                ),
            ],
            total_iterations=1,
            elapsed_seconds=1.0,
        )
        report = generate_report(result)
        assert "AutoConfig Tuning Report" in report
        assert "40.0%" in report
        assert "intake.base_salience" in report


# ── Integration: Simulator + Engine ──────────────────────────────


@pytest.mark.asyncio
async def test_simulator_short_term():
    """Run the short_term_recall scenario and verify it completes."""
    from alive_memory.autotune.simulator import run_scenario

    scenarios = load_scenarios("builtin")
    short_term = next(s for s in scenarios if s.name == "short_term_recall")

    cfg = AliveConfig()
    result = await run_scenario(short_term, cfg)

    assert result.scenario_name == "short_term_recall"
    assert result.moments_recorded > 0
    assert len(result.recall_results) > 0
    assert result.elapsed_real_ms >= 0


@pytest.mark.asyncio
async def test_autotune_3_iterations():
    """Run a 3-iteration autotune and verify it produces a result."""
    from alive_memory.autotune.engine import autotune

    result = await autotune(
        autotune_config=AutotuneConfig(budget=3, verbose=False),
    )

    assert result.total_iterations == 3
    assert len(result.experiments) == 3
    assert result.best_composite <= result.baseline_composite
    assert result.best_config  # non-empty


@pytest.mark.asyncio
async def test_alive_memory_autotune_method():
    """Test the AliveMemory.autotune() convenience method."""
    from alive_memory import AliveMemory

    async with AliveMemory(storage=":memory:") as mem:
        result = await mem.autotune(budget=2, verbose=False)
        assert result.total_iterations == 2
        assert result.best_config
