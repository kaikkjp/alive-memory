"""Tests for sim.visitors.llm_visitor — Tier 2 LLM visitor generation.

Validates:
- Persona generation and parsing (with cache)
- Turn generation with sliding window context
- Token budget enforcement (1500 per visit)
- Max turn enforcement by temperament
- Fallback persona generation when LLM fails
- Cache hit/miss tracking
- Visitor cache JSONL persistence
- Integration with scheduler (social scenario produces Tier 2 visitors)
"""

import json
import os
import tempfile

import pytest
import pytest_asyncio

from sim.visitors.llm_visitor import (
    LLMVisitorGenerator,
    VisitorPersona,
    VisitorTurn,
    _MAX_TURNS,
    _TEMPERAMENT_PATIENCE,
)
from sim.visitors.visitor_cache import VisitorCache
from sim.visitors.archetypes import (
    ARCHETYPES,
    pick_archetype,
    pick_goal,
)
from sim.visitors.models import VisitorTier
from sim.visitors.scheduler import VisitorScheduler


# -- Mock LLM that returns structured JSON --

class MockVisitorLLM:
    """Mock LLM that returns valid persona/turn JSON for testing."""

    def __init__(self, persona_data: dict | None = None, turn_data: dict | None = None):
        self.persona_data = persona_data or {
            "name": "Test Visitor",
            "backstory": "A test visitor for unit tests.",
            "goal": "browse",
            "budget_yen": 3000,
            "expertise": "novice",
            "temperament": "patient",
            "emotional_state": "curious",
            "memory_anchor": "the dusty shelves",
        }
        self.turn_data = turn_data or {
            "text": "That's interesting. Tell me more.",
            "intent": "chatting",
            "should_exit": False,
            "exit_reason": None,
        }
        self.call_count = 0
        self.calls: list[dict] = []

    async def complete(self, messages, system=None, call_site="default",
                       max_tokens=4096, temperature=0.0, **kwargs):
        self.call_count += 1
        self.calls.append({
            "call_site": call_site,
            "max_tokens": max_tokens,
            "temperature": temperature,
        })

        if call_site == "visitor_persona":
            text = json.dumps(self.persona_data)
        elif call_site == "visitor_turn":
            text = json.dumps(self.turn_data)
        else:
            text = json.dumps(self.persona_data)

        return {
            "content": [{"text": text}],
            "usage": {"output_tokens": 50, "cost_usd": 0.001},
        }


class MockBrokenLLM:
    """Mock LLM that returns invalid responses."""

    async def complete(self, **kwargs):
        return {"content": [{"text": "this is not json at all!!!"}]}


# -- Fixtures --

@pytest.fixture
def tmp_cache_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def cache(tmp_cache_dir):
    return VisitorCache(cache_dir=tmp_cache_dir)


@pytest.fixture
def mock_llm():
    return MockVisitorLLM()


@pytest.fixture
def generator(mock_llm, cache):
    return LLMVisitorGenerator(llm=mock_llm, cache=cache, seed=42)


# -- VisitorPersona --

class TestVisitorPersona:
    """Tests for VisitorPersona dataclass."""

    def test_from_dict_full(self):
        data = {
            "name": "Tanaka",
            "backstory": "A regular.",
            "goal": "buy",
            "budget_yen": 10000,
            "expertise": "expert",
            "temperament": "skeptical",
            "emotional_state": "neutral",
            "memory_anchor": "the rare card",
        }
        p = VisitorPersona.from_dict(data)
        assert p.name == "Tanaka"
        assert p.goal == "buy"
        assert p.budget_yen == 10000
        assert p.temperament == "skeptical"

    def test_from_dict_budget_with_comma(self):
        """P1 fix: LLMs may return budget_yen as '5,000'."""
        p = VisitorPersona.from_dict({"budget_yen": "5,000"})
        assert p.budget_yen == 5000

    def test_from_dict_budget_garbage(self):
        """P1 fix: totally invalid budget falls back to default."""
        p = VisitorPersona.from_dict({"budget_yen": "lots of money"})
        assert p.budget_yen == 5000

    def test_from_dict_budget_none(self):
        p = VisitorPersona.from_dict({"budget_yen": None})
        assert p.budget_yen == 5000

    def test_from_dict_missing_fields(self):
        p = VisitorPersona.from_dict({})
        assert p.name == "Visitor"
        assert p.goal == "browse"
        assert p.budget_yen == 5000
        assert p.temperament == "patient"

    def test_roundtrip(self):
        p = VisitorPersona(name="Yuki", goal="sell", budget_yen=8000)
        data = p.to_dict()
        p2 = VisitorPersona.from_dict(data)
        assert p2.name == "Yuki"
        assert p2.goal == "sell"
        assert p2.budget_yen == 8000


class TestVisitorTurn:
    """Tests for VisitorTurn dataclass."""

    def test_from_dict_exit(self):
        data = {
            "text": "Goodbye!",
            "intent": "leaving",
            "should_exit": True,
            "exit_reason": "goal_satisfied",
        }
        t = VisitorTurn.from_dict(data)
        assert t.should_exit is True
        assert t.exit_reason == "goal_satisfied"

    def test_from_dict_defaults(self):
        t = VisitorTurn.from_dict({})
        assert t.text == ""
        assert t.should_exit is False
        assert t.exit_reason is None


# -- Persona Generation --

class TestPersonaGeneration:
    """Tests for LLMVisitorGenerator.generate_persona()."""

    @pytest.mark.asyncio
    async def test_generates_persona(self, generator, mock_llm):
        persona = await generator.generate_persona("v001", "regular", "buy")
        assert persona.name == "Test Visitor"
        assert persona.goal == "browse"
        assert mock_llm.call_count == 1
        assert mock_llm.calls[0]["call_site"] == "visitor_persona"

    @pytest.mark.asyncio
    async def test_persona_max_tokens(self, generator, mock_llm):
        await generator.generate_persona("v002")
        assert mock_llm.calls[0]["max_tokens"] == 300

    @pytest.mark.asyncio
    async def test_persona_cached_on_second_call(self, generator, mock_llm):
        await generator.generate_persona("v003")
        assert mock_llm.call_count == 1
        await generator.generate_persona("v003")
        assert mock_llm.call_count == 1  # Cache hit

    @pytest.mark.asyncio
    async def test_different_visitors_different_calls(self, generator, mock_llm):
        await generator.generate_persona("v004")
        await generator.generate_persona("v005")
        assert mock_llm.call_count == 2

    @pytest.mark.asyncio
    async def test_fallback_on_broken_llm(self, cache):
        gen = LLMVisitorGenerator(llm=MockBrokenLLM(), cache=cache, seed=42)
        persona = await gen.generate_persona("v006")
        # Should get a fallback persona, not crash
        assert persona.name != ""
        assert persona.goal in ("buy", "browse", "chat", "learn", "sell")


# -- Turn Generation --

class TestTurnGeneration:
    """Tests for LLMVisitorGenerator.generate_turn()."""

    @pytest.mark.asyncio
    async def test_generates_turn(self, generator, mock_llm):
        persona = VisitorPersona(name="Test", goal="buy", temperament="patient")
        turn = await generator.generate_turn("v010", persona, 0, [])
        assert turn.text == "That's interesting. Tell me more."
        assert turn.intent == "chatting"
        assert mock_llm.call_count == 1
        assert mock_llm.calls[0]["call_site"] == "visitor_turn"

    @pytest.mark.asyncio
    async def test_turn_max_tokens(self, generator, mock_llm):
        persona = VisitorPersona(name="Test", goal="buy")
        await generator.generate_turn("v011", persona, 0, [])
        assert mock_llm.calls[0]["max_tokens"] == 150

    @pytest.mark.asyncio
    async def test_turn_cached_on_same_context(self, generator, mock_llm):
        persona = VisitorPersona(name="Test", goal="buy")
        await generator.generate_turn("v012", persona, 0, [], "hello")
        assert mock_llm.call_count == 1
        await generator.generate_turn("v012", persona, 0, [], "hello")
        assert mock_llm.call_count == 1  # Cache hit

    @pytest.mark.asyncio
    async def test_turn_not_cached_different_response(self, generator, mock_llm):
        persona = VisitorPersona(name="Test", goal="buy")
        await generator.generate_turn("v013", persona, 0, [], "hello")
        await generator.generate_turn("v013", persona, 0, [], "goodbye")
        assert mock_llm.call_count == 2

    @pytest.mark.asyncio
    async def test_max_turns_forces_exit(self, generator, mock_llm):
        persona = VisitorPersona(name="Test", temperament="patient")
        max_t = _MAX_TURNS["patient"]
        turn = await generator.generate_turn("v014", persona, max_t, [])
        assert turn.should_exit is True
        assert turn.exit_reason == "patience_exhausted"
        assert mock_llm.call_count == 0  # No LLM call needed

    @pytest.mark.asyncio
    async def test_token_budget_forces_exit(self, generator, mock_llm):
        persona = VisitorPersona(name="Test")
        # Exhaust token budget
        generator._token_budget_used["v015"] = 1200
        turn = await generator.generate_turn("v015", persona, 1, [])
        assert turn.should_exit is True
        assert turn.exit_reason == "budget_depleted"
        assert mock_llm.call_count == 0

    @pytest.mark.asyncio
    async def test_fallback_turn_on_broken_llm(self, cache):
        gen = LLMVisitorGenerator(llm=MockBrokenLLM(), cache=cache, seed=42)
        persona = VisitorPersona(name="Test")
        turn = await gen.generate_turn("v016", persona, 0, [])
        # Should extract raw text as fallback
        assert turn.text != ""
        assert turn.intent == "chatting"


# -- Visitor Cache --

class TestVisitorCache:
    """Tests for VisitorCache JSONL persistence."""

    def test_persona_roundtrip(self, cache):
        cache.put_persona("v020", 42, {"name": "Cached", "goal": "buy"})
        result = cache.get_persona("v020", 42)
        assert result is not None
        assert result["name"] == "Cached"

    def test_persona_miss(self, cache):
        result = cache.get_persona("nonexistent", 42)
        assert result is None

    def test_persona_different_seed_miss(self, cache):
        cache.put_persona("v021", 42, {"name": "Seed42"})
        result = cache.get_persona("v021", 99)
        assert result is None

    def test_persona_persistence(self, tmp_cache_dir):
        # Write with one cache instance
        c1 = VisitorCache(cache_dir=tmp_cache_dir)
        c1.put_persona("v022", 42, {"name": "Persistent"})

        # Read with a fresh cache instance
        c2 = VisitorCache(cache_dir=tmp_cache_dir)
        result = c2.get_persona("v022", 42)
        assert result is not None
        assert result["name"] == "Persistent"

    def test_turn_roundtrip(self, cache):
        cache.put_turn("v023", 0, "hello", {"text": "Hi!", "intent": "greeting"})
        result = cache.get_turn("v023", 0, "hello")
        assert result is not None
        assert result["text"] == "Hi!"

    def test_turn_miss(self, cache):
        result = cache.get_turn("v024", 0, "hello")
        assert result is None

    def test_stats(self, cache):
        cache.get_persona("miss", 42)
        cache.put_persona("hit", 42, {"name": "X"})
        cache.get_persona("hit", 42)

        stats = cache.stats()
        assert stats["persona_misses"] == 1
        assert stats["persona_hits"] == 1

    def test_clear(self, cache):
        cache.put_persona("v025", 42, {"name": "Gone"})
        cache.put_turn("v025", 0, "x", {"text": "bye"})
        cache.clear()
        assert cache.get_persona("v025", 42) is None
        assert cache.get_turn("v025", 0, "x") is None

    def test_list_personas(self, cache):
        cache.put_persona("v026", 42, {"name": "A"})
        cache.put_persona("v027", 42, {"name": "B"})
        personas = cache.list_personas(42)
        assert len(personas) == 2
        names = {p["name"] for p in personas}
        assert names == {"A", "B"}


# -- Archetypes --

class TestArchetypes:
    """Tests for archetype definitions and selection."""

    def test_ten_archetypes_defined(self):
        assert len(ARCHETYPES) == 10

    def test_all_have_required_fields(self):
        for a in ARCHETYPES.values():
            assert a.archetype_id
            assert a.name
            assert a.traits is not None
            assert len(a.goal_templates) > 0
            assert a.weight > 0

    def test_pick_archetype_deterministic(self):
        import random
        r1 = random.Random(42)
        r2 = random.Random(42)
        a1 = pick_archetype(r1)
        a2 = pick_archetype(r2)
        assert a1.archetype_id == a2.archetype_id

    def test_pick_goal_from_templates(self):
        import random
        rng = random.Random(42)
        for a in ARCHETYPES.values():
            goal = pick_goal(a, rng)
            assert goal in a.goal_templates


# -- Scheduler Integration --

class TestSchedulerIntegration:
    """Tests for Tier 2 visitor scheduling in social scenario."""

    def test_social_scenario_has_tier2(self):
        s = VisitorScheduler(scenario="social", seed=42)
        arrivals = s.generate(num_cycles=1000)
        tier2 = [a for a in arrivals if a.visitor.tier == VisitorTier.TIER_2]
        assert len(tier2) > 0, "Social scenario should produce Tier 2 visitors"

    def test_standard_scenario_no_tier2(self):
        s = VisitorScheduler(scenario="standard", seed=42)
        arrivals = s.generate(num_cycles=1000)
        tier2 = [a for a in arrivals if a.visitor.tier == VisitorTier.TIER_2]
        assert len(tier2) == 0, "Standard scenario should have no Tier 2 visitors"

    def test_social_tier2_fraction(self):
        """Social scenario should have ~50% Tier 2 visitors."""
        s = VisitorScheduler(scenario="social", seed=42)
        arrivals = s.generate(num_cycles=1000)
        total = len(arrivals)
        tier2 = len([a for a in arrivals if a.visitor.tier == VisitorTier.TIER_2])
        if total > 10:  # Only check if enough samples
            fraction = tier2 / total
            assert 0.2 < fraction < 0.8, (
                f"Tier 2 fraction {fraction:.2f} outside expected range "
                f"(got {tier2}/{total})"
            )

    def test_stress_scenario_high_tier2(self):
        """Stress scenario should have ~80% Tier 2 visitors."""
        s = VisitorScheduler(scenario="stress", seed=42)
        arrivals = s.generate(num_cycles=500)
        total = len(arrivals)
        tier2 = len([a for a in arrivals if a.visitor.tier == VisitorTier.TIER_2])
        if total > 10:
            fraction = tier2 / total
            assert fraction > 0.5, (
                f"Stress tier2 fraction {fraction:.2f} too low "
                f"(got {tier2}/{total})"
            )

    def test_isolation_no_visitors(self):
        s = VisitorScheduler(scenario="isolation", seed=42)
        arrivals = s.generate(num_cycles=1000)
        assert len(arrivals) == 0


# -- Runner Init (P0 regression) --

class TestRunnerInit:
    """P0 fix: SimulationRunner must not crash on social scenario init."""

    def test_social_scenario_construction(self):
        """_tier2_visitor_ids must exist before _build_v2_scenario runs."""
        from sim.runner import SimulationRunner
        # This crashed before the fix with AttributeError
        runner = SimulationRunner(
            scenario="social", num_cycles=100, llm_mode="mock", seed=42,
        )
        assert len(runner._tier2_visitor_ids) > 0

    def test_stress_scenario_construction(self):
        from sim.runner import SimulationRunner
        runner = SimulationRunner(
            scenario="stress", num_cycles=100, llm_mode="mock", seed=42,
        )
        assert len(runner._tier2_visitor_ids) > 0

    def test_standard_scenario_no_tier2_ids(self):
        from sim.runner import SimulationRunner
        runner = SimulationRunner(
            scenario="standard", num_cycles=100, llm_mode="mock", seed=42,
        )
        assert len(runner._tier2_visitor_ids) == 0


# -- Temperament Config --

class TestTemperamentConfig:
    """Tests for temperament-based turn limits."""

    def test_patient_has_most_turns(self):
        assert _MAX_TURNS["patient"] > _MAX_TURNS["shy"]

    def test_patient_highest_patience(self):
        assert _TEMPERAMENT_PATIENCE["patient"] > _TEMPERAMENT_PATIENCE["skeptical"]

    def test_all_temperaments_have_config(self):
        for t in ["patient", "eager", "skeptical", "shy"]:
            assert t in _MAX_TURNS
            assert t in _TEMPERAMENT_PATIENCE
