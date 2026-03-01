"""sim.runner — SimulationRunner orchestrates experiments.

Runs a full experiment with a specific architecture variant, scenario,
and LLM mode. Self-contained — does not depend on the production
Heartbeat class. Operates its own lightweight cycle loop.

Usage:
    from sim.runner import SimulationRunner
    runner = SimulationRunner(variant="full", scenario="standard", num_cycles=1000)
    result = await runner.run()
"""

from __future__ import annotations

import json
import random
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sim.clock import SimulatedClock
from sim.content_pool import SimContentPool
from sim.db import InMemoryDB
from sim.scenario import ScenarioEvent, ScenarioManager
from sim.visitors.archetypes import ARCHETYPES
from sim.visitors.llm_visitor import LLMVisitorEngine
from sim.visitors.models import VisitorTier
from sim.visitors.returning import ReturningVisitorManager
from sim.visitors.scheduler import VisitorScheduler, SCENARIO_CONFIGS
from sim.visitors.state_machine import VisitorStateMachine


@dataclass
class CycleResult:
    """Result of a single simulation cycle."""
    cycle_num: int
    timestamp: str
    cycle_type: str = "idle"         # idle | dialogue | browse | post | journal | rest | sleep
    action: str | None = None
    dialogue: str | None = None
    internal_monologue: str = ""
    expression: str = "neutral"
    has_visitor: bool = False
    drives: dict = field(default_factory=dict)
    intentions: list[dict] = field(default_factory=list)
    memory_updates: list[dict] = field(default_factory=list)
    resonance: bool = False
    sleep_triggered: bool = False
    budget_usd_daily_cap: float = 1.0
    budget_spent_usd: float = 0.0
    budget_remaining_usd: float = 1.0
    budget_mode: str = "normal"  # normal | emergency
    budget_after_sleep_usd: float | None = None
    raw_llm_output: dict | None = None


@dataclass
class SimulationResult:
    """Complete results of a simulation run."""
    variant: str
    scenario: str
    num_cycles: int
    seed: int
    llm_mode: str
    cycles: list[CycleResult] = field(default_factory=list)
    drives_history: list[dict] = field(default_factory=list)
    visitors: dict = field(default_factory=dict)  # visitor_id -> visit info
    sleep_cycles: list[int] = field(default_factory=list)
    total_dialogues: int = 0
    total_browses: int = 0
    total_posts: int = 0
    total_journals: int = 0
    daily_budget_usd: float = 1.0
    budget_rest_cycles: int = 0
    content_pool_stats: dict = field(default_factory=dict)
    llm_stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "variant": self.variant,
            "scenario": self.scenario,
            "num_cycles": self.num_cycles,
            "seed": self.seed,
            "llm_mode": self.llm_mode,
            "total_dialogues": self.total_dialogues,
            "total_browses": self.total_browses,
            "total_posts": self.total_posts,
            "total_journals": self.total_journals,
            "sleep_cycles": len(self.sleep_cycles),
            "daily_budget_usd": self.daily_budget_usd,
            "budget_rest_cycles": self.budget_rest_cycles,
            "content_pool_stats": self.content_pool_stats,
            "visitors_seen": len(self.visitors),
            "llm_stats": self.llm_stats,
            "cycles": [
                {
                    "cycle": c.cycle_num,
                    "type": c.cycle_type,
                    "action": c.action,
                    "has_visitor": c.has_visitor,
                    "dialogue": c.dialogue,
                    "monologue": c.internal_monologue[:500] if c.internal_monologue else "",
                    "expression": c.expression,
                    "resonance": c.resonance,
                    "budget_usd_daily_cap": c.budget_usd_daily_cap,
                    "budget_spent_usd": c.budget_spent_usd,
                    "budget_remaining_usd": c.budget_remaining_usd,
                    "budget_mode": c.budget_mode,
                    "budget_after_sleep_usd": c.budget_after_sleep_usd,
                    "drives": c.drives,
                    "memory_updates": c.memory_updates,
                    "intentions": c.intentions,
                }
                for c in self.cycles
            ],
            "drives_history": self.drives_history,
        }


class SimulationRunner:
    """Runs a full experiment with a specific architecture variant."""

    # Cortex output schema — copied from pipeline/cortex.py CORTEX_SYSTEM.
    # Kept in sync manually; the sim needs the same JSON contract so real
    # LLMs (cached mode) return structured output instead of prose.
    _OUTPUT_SCHEMA = """\
OUTPUT SCHEMA:
{
  "internal_monologue": "your private thoughts (20-50 words)",
  "dialogue": "what you say out loud (or null for silence)",
  "dialogue_language": "en|ja|mixed",
  "expression": "neutral|listening|almost_smile|thinking|amused|low|surprised|genuine_smile",
  "body_state": "sitting|reaching_back|leaning_forward|holding_object|writing|hands_on_cup",
  "gaze": "at_visitor|at_object|away_thinking|down|window",
  "resonance": false,
  "intentions": [
    {
      "action": "any verb — e.g. speak, write_journal, or your own",
      "target": "visitor|visitor:ID|shelf|journal|self|web|x_timeline|telegram",
      "content": "what you'd say, write, or do",
      "impulse": 0.8
    }
  ],
  "actions": [
    {
      "type": "accept_gift|decline_gift|show_item|place_item|rearrange|open_shop|close_shop|write_journal|post_x_draft|end_engagement|browse_web|post_x|reply_x|post_x_image|tg_send|tg_send_image",
      "detail": {}
    }
  ],
  "memory_updates": [
    {
      "type": "visitor_impression",
      "content": {"summary": "one-line impression of this visitor", "emotional_imprint": "how they make you feel"}
    },
    {
      "type": "trait_observation",
      "content": {"trait_category": "taste|personality|topic|relationship", "trait_key": "short label", "trait_value": "what you observed"}
    },
    {
      "type": "totem_create|totem_update|journal_entry|self_discovery|collection_add",
      "content": {}
    },
    {
      "type": "thread_create",
      "content": {"thread_type": "question|project|anticipation|unresolved|ritual", "title": "short title", "priority": 0.5, "initial_thought": "what you're thinking about this", "tags": []}
    },
    {
      "type": "thread_update",
      "content": {"thread_id": "id or null", "title": "title if no id", "content": "updated thinking", "reason": "why you're revisiting this"}
    },
    {
      "type": "thread_close",
      "content": {"thread_id": "id or null", "title": "title if no id", "resolution": "how this resolved"}
    }
  ],
  "next_cycle_hints": ["optional hints for what she might do next"]
}"""

    def __init__(
        self,
        variant: str = "full",
        scenario: str = "standard",
        num_cycles: int = 1000,
        llm_mode: str = "mock",
        seed: int = 42,
        output_dir: str = "sim/results",
        start_time: str = "2026-02-01T09:00:00+09:00",
        daily_budget: float = 1.0,
        block_sleep: bool = False,
        verbose: bool = False,
    ):
        self.variant = variant
        self.scenario_name = scenario
        self.num_cycles = num_cycles
        self.llm_mode = llm_mode
        self.seed = seed
        self.output_dir = Path(output_dir)
        self.block_sleep = block_sleep
        self.verbose = verbose
        self.daily_budget = max(0.01, float(daily_budget))

        # Initialize components
        self.clock = SimulatedClock(start=start_time)
        self.db: InMemoryDB | None = None
        self.llm = self._init_llm(llm_mode, seed)
        self.pipeline = self._init_pipeline(variant)

        # Runtime state
        self._drives = {
            "social_hunger": 0.5,
            "curiosity": 0.5,
            "expression_need": 0.3,
            "rest_need": 0.2,
            "energy": 1.0,  # display-only, derived from budget
            "mood_valence": 0.0,
            "mood_arousal": 0.3,
        }
        self._budget_spent_since_sleep = 0.0
        self._engagement = {
            "status": "none",
            "visitor_id": None,
            "turn_count": 0,
        }
        self._visitor_history: dict[str, dict] = {}  # visitor_id -> info
        self._sync_display_energy_from_budget()

        # Content pool — synthetic RSS feed for the inner life loop
        self.content_pool = SimContentPool(seed=seed)
        self._last_notifications: list[dict] = []  # current cycle's notifications

        # Tier 2 LLM visitor engine + dynamic event queue
        # Must be initialized before _build_v2_scenario which populates them
        self._llm_visitor_engine: LLMVisitorEngine | None = None
        self._pending_visitor_events: list[ScenarioEvent] = []
        self._tier2_visitor_ids: set[str] = set()
        self._tier2_visitors: dict[str, Any] = {}  # visitor_id -> VisitorInstance
        self._returning_memory: dict[str, str] = {}  # visitor_id -> memory_stub
        self._returning_mgr: ReturningVisitorManager | None = None

        # Taste formation experiment (TASK-093)
        self._taste_scenario = None
        self._taste_market = None
        self._taste_evaluator = None

        if scenario in SCENARIO_CONFIGS:
            cfg = SCENARIO_CONFIGS[scenario]
            if cfg.tier2_enabled:
                self._llm_visitor_engine = LLMVisitorEngine(
                    llm_mode=llm_mode,
                    seed=seed,
                )

        # V2 scenarios use Poisson scheduler; v1 uses hardcoded ScenarioManager
        if scenario == "taste_formation":
            self._build_taste_scenario(seed)
            self.scenario = ScenarioManager([], name="taste_formation")
        elif scenario in SCENARIO_CONFIGS:
            self.scenario = self._build_v2_scenario(scenario, seed, num_cycles)
        else:
            self.scenario = ScenarioManager.load(scenario)

    def _init_llm(self, mode: str, seed: int):
        """Initialize the LLM backend."""
        if mode == "mock":
            from sim.llm.mock import MockCortex
            return MockCortex(seed=seed)
        elif mode == "cached":
            from sim.llm.cached import CachedCortex
            return CachedCortex(variant=self.variant)
        else:
            raise ValueError(f"Unknown LLM mode: {mode}. Use 'mock' or 'cached'.")

    def _init_pipeline(self, variant: str):
        """Initialize the pipeline variant."""
        if variant == "full":
            return FullPipeline()
        elif variant == "stateless":
            from sim.baselines.stateless import StatelessBaseline
            return StatelessBaseline()
        elif variant == "react":
            from sim.baselines.react_agent import ReActBaseline
            return ReActBaseline()
        elif variant.startswith("no_"):
            from sim.variants import AblatedPipeline
            return AblatedPipeline(remove=variant[3:])
        else:
            raise ValueError(f"Unknown variant: {variant}")

    def _build_v2_scenario(
        self, scenario: str, seed: int, num_cycles: int
    ) -> ScenarioManager:
        """Build a ScenarioManager from Poisson-scheduled visitor arrivals.

        Uses the state machine to generate multi-turn dialogue sequences
        for each visitor, spread across their visit duration.
        """
        scheduler = VisitorScheduler(scenario=scenario, seed=seed)
        arrivals = scheduler.generate(num_cycles=num_cycles)

        events: list[ScenarioEvent] = []
        for arrival in arrivals:
            v = arrival.visitor
            source = v.visitor_id
            name = v.name

            # Visitor arrives — include tier in payload for the run loop
            events.append(ScenarioEvent(arrival.cycle, "visitor_arrive", {
                "source": source,
                "name": name,
                "channel": "sim",
                "tier": v.tier.value,
            }))

            # Tier 2 visitors get dynamic dialogue from LLMVisitorEngine
            # during the run loop — only pre-generate for Tier 1.
            if v.tier == VisitorTier.TIER_2:
                # Track Tier 2 visitors for the run loop
                self._tier2_visitor_ids.add(source)
                # Store visitor instance for the engine
                self._tier2_visitors[source] = v
            else:
                # Tier 1: generate state-machine-driven dialogue turns
                archetype = ARCHETYPES.get(v.archetype_id) if v.archetype_id else None
                if archetype:
                    visit_rng = random.Random(seed + arrival.cycle)
                    sm = VisitorStateMachine(v, archetype, visit_rng)
                    visit_turns = sm.generate_visit()

                    # Spread turns across the visit duration
                    duration = arrival.visit_duration_cycles
                    if visit_turns:
                        # Space turns evenly, first turn at arrival cycle
                        step = max(1, duration // max(1, len(visit_turns)))
                        for i, turn in enumerate(visit_turns):
                            turn_cycle = min(
                                arrival.cycle + i * step,
                                arrival.cycle + duration - 1,
                                num_cycles - 1,
                            )
                            events.append(ScenarioEvent(
                                turn_cycle, "visitor_message", {
                                    "source": source,
                                    "content": turn.text,
                                },
                            ))
                else:
                    # Fallback for visitors without archetype
                    events.append(ScenarioEvent(
                        arrival.cycle, "visitor_message", {
                            "source": source,
                            "content": "Hello! What an interesting shop.",
                        },
                    ))

            # Visitor leaves after their visit duration
            leave_cycle = min(
                arrival.cycle + arrival.visit_duration_cycles,
                num_cycles - 1,
            )
            events.append(ScenarioEvent(leave_cycle, "visitor_leave", {
                "source": source,
            }))

        # Tier 3: schedule returning visitors when enabled
        cfg = SCENARIO_CONFIGS[scenario]
        if cfg.tier3_enabled and cfg.tier3_return_rate > 0:
            returning_mgr = ReturningVisitorManager(
                return_rate=cfg.tier3_return_rate, seed=seed,
            )
            self._returning_mgr = returning_mgr
            return_arrivals = returning_mgr.schedule_returns(
                arrivals, num_cycles,
            )

            for arrival in return_arrivals:
                v = arrival.visitor
                source = v.visitor_id
                name = v.name

                # Store memory stub for prompt injection
                if v.memory_stub:
                    self._returning_memory[source] = v.memory_stub

                # Returning visitor arrives with memory context
                events.append(ScenarioEvent(arrival.cycle, "visitor_arrive", {
                    "source": source,
                    "name": name,
                    "channel": "sim",
                    "tier": v.tier.value,
                    "is_return": True,
                    "memory_stub": v.memory_stub,
                    "visit_count": len(v.visit_history),
                }))

                # Generate state-machine dialogue (same as Tier 1)
                archetype = (
                    ARCHETYPES.get(v.archetype_id)
                    if v.archetype_id else None
                )
                if archetype:
                    visit_rng = random.Random(seed + arrival.cycle)
                    sm = VisitorStateMachine(v, archetype, visit_rng)
                    visit_turns = sm.generate_visit()

                    if visit_turns:
                        # Replace entering text with return-specific dialogue
                        enter_text = returning_mgr.get_return_entering_text(
                            v, visit_rng,
                        )
                        duration = arrival.visit_duration_cycles
                        step = max(1, duration // max(1, len(visit_turns)))

                        for i, turn in enumerate(visit_turns):
                            text = enter_text if i == 0 else turn.text
                            turn_cycle = min(
                                arrival.cycle + i * step,
                                arrival.cycle + duration - 1,
                                num_cycles - 1,
                            )
                            events.append(ScenarioEvent(
                                turn_cycle, "visitor_message", {
                                    "source": source,
                                    "content": text,
                                },
                            ))
                else:
                    events.append(ScenarioEvent(
                        arrival.cycle, "visitor_message", {
                            "source": source,
                            "content": "Hello again. I was here before.",
                        },
                    ))

                # Returning visitor leaves
                leave_cycle = min(
                    arrival.cycle + arrival.visit_duration_cycles,
                    num_cycles - 1,
                )
                events.append(ScenarioEvent(leave_cycle, "visitor_leave", {
                    "source": source,
                }))

            # Adversarial: inject doppelganger arrivals
            adversarial_arrivals = returning_mgr.schedule_adversarial(
                return_arrivals, num_cycles,
            )
            for arrival in adversarial_arrivals:
                v = arrival.visitor
                source = v.visitor_id

                events.append(ScenarioEvent(arrival.cycle, "visitor_arrive", {
                    "source": source,
                    "name": v.name,
                    "channel": "sim",
                    "tier": v.tier.value,
                    "is_return": False,
                    "adversarial": True,
                }))

                # Doppelganger dialogue from adversarial templates
                visit_rng = random.Random(seed + arrival.cycle)
                enter_text = returning_mgr.get_return_entering_text(
                    v, visit_rng,
                )
                events.append(ScenarioEvent(
                    arrival.cycle, "visitor_message", {
                        "source": source,
                        "content": enter_text,
                    },
                ))

                leave_cycle = min(
                    arrival.cycle + arrival.visit_duration_cycles,
                    num_cycles - 1,
                )
                events.append(ScenarioEvent(leave_cycle, "visitor_leave", {
                    "source": source,
                }))

            if self.verbose and return_arrivals:
                adv_count = len(adversarial_arrivals)
                adv_str = f" + {adv_count} adversarial" if adv_count else ""
                print(f"[Sim] Tier 3: {len(return_arrivals)} return visits "
                      f"from {returning_mgr.flagged_count} flagged visitors"
                      f"{adv_str}")

        if self.verbose:
            stats = scheduler.stats(arrivals, num_cycles)
            print(f"[Sim] V2 scenario '{scenario}': "
                  f"{stats['total_visitors']} visitors, "
                  f"{stats['visitors_per_day']:.1f}/day, "
                  f"by_part={stats['by_day_part']}")

        return ScenarioManager(events, name=scenario)

    def _budget_remaining(self) -> float:
        """Remaining dollars since last sleep reset."""
        return max(0.0, self.daily_budget - self._budget_spent_since_sleep)

    def _sync_display_energy_from_budget(self):
        """Energy is a display proxy: remaining budget ratio in [0, 1]."""
        if self.daily_budget <= 0:
            self._drives["energy"] = 0.0
            return
        self._drives["energy"] = max(0.0, min(1.0, self._budget_remaining() / self.daily_budget))

    async def run(self) -> SimulationResult:
        """Run all cycles, collect results."""
        # Initialize DB
        self.db = await InMemoryDB.create()

        # Seed initial drives into DB
        await self._save_drives_to_db()

        result = SimulationResult(
            variant=self.variant,
            scenario=self.scenario_name,
            num_cycles=self.num_cycles,
            seed=self.seed,
            llm_mode=self.llm_mode,
            daily_budget_usd=self.daily_budget,
        )

        for cycle_num in range(self.num_cycles):
            # Advance simulated time
            self.clock.advance(minutes=5)

            # Get scenario events for this cycle + any pending LLM visitor events
            scenario_events = self.scenario.get_events(cycle_num)
            if self._pending_visitor_events:
                # Filter out pending speech from visitors who leave this
                # cycle — prevents "ghost replies" after disconnect.
                leaving_sources = {
                    se.payload.get("source") for se in scenario_events
                    if se.event_type == "visitor_leave"
                }
                for pe in self._pending_visitor_events:
                    if pe.payload.get("source") not in leaving_sources:
                        scenario_events.append(pe)
                self._pending_visitor_events.clear()

            # Handle meta-events (set_drives, inject_thread, block_sleep)
            pipeline_events = []
            for se in scenario_events:
                if se.event_type == "set_drives":
                    self._apply_drive_overrides(se.payload)
                    await self._save_drives_to_db()
                elif se.event_type == "inject_thread":
                    await self._inject_thread(se.payload)
                elif se.event_type == "block_sleep":
                    self.block_sleep = se.payload.get("enabled", True)
                elif se.event_type == "unblock_sleep":
                    self.block_sleep = False
                else:
                    event_dict = se.to_pipeline_event(self.clock.now())
                    pipeline_events.append(event_dict)
                    await self._inject_event(event_dict)

            # Generate greetings for Tier 2 visitors arriving this cycle
            await self._handle_tier2_arrivals(pipeline_events, cycle_num)

            # Handle visitor state from events
            self._process_visitor_events(pipeline_events)
            self._sync_display_energy_from_budget()

            # Taste formation experiment: intercept cycle based on phase
            if self._taste_scenario:
                taste_type = self._taste_scenario.cycle_type(cycle_num)
                if taste_type == "browse":
                    cycle_result = await self._run_taste_browse_cycle(
                        cycle_num,
                    )
                    result.cycles.append(cycle_result)
                    result.drives_history.append({
                        "cycle": cycle_num, **self._drives,
                    })
                    if self.verbose:
                        evals = self._taste_scenario.evaluations_today
                        cap = self._taste_scenario.capital
                        print(f"  [{cycle_num:04d}] taste_browse "
                              f"evals={evals} capital={cap}¥")
                    continue
                elif taste_type == "outcome":
                    resolved = self._taste_scenario.resolve_pending_outcomes(
                        cycle_num,
                    )
                    for outcome in resolved:
                        await self.db.record_taste_outcome(
                            item_id=outcome["item_id"],
                            eval_id=outcome.get("eval_id"),
                            cycle_acquired=outcome["cycle_acquired"],
                            cycle_outcome=outcome["cycle_outcome"],
                            buy_price=outcome["buy_price"],
                            sell_price=outcome.get("sell_price"),
                            profit=outcome.get("profit", 0),
                            time_to_sell=outcome.get("time_to_sell"),
                            outcome_category=outcome.get(
                                "outcome_category", "loss",
                            ),
                        )
                    cycle_result = CycleResult(
                        cycle_num=cycle_num,
                        timestamp=self.clock.now().isoformat(),
                        cycle_type="taste_outcome",
                        drives=dict(self._drives),
                    )
                    result.cycles.append(cycle_result)
                    result.drives_history.append({
                        "cycle": cycle_num, **self._drives,
                    })
                    if self.verbose and resolved:
                        print(f"  [{cycle_num:04d}] taste_outcome "
                              f"resolved={len(resolved)}")
                    continue
                elif taste_type == "sleep":
                    self._taste_scenario.sleep()
                    # Fall through to normal sleep check
                # else: "normal" — fall through to _run_cycle

            # Check sleep window
            if not self.block_sleep and self.pipeline.should_sleep(self.clock):
                pre_sleep_drives = dict(self._drives)
                budget_before = self._budget_remaining()
                # Sleep boundary resets the spend window.
                self._budget_spent_since_sleep = 0.0
                self._sync_display_energy_from_budget()
                cycle_result = CycleResult(
                    cycle_num=cycle_num,
                    timestamp=self.clock.now().isoformat(),
                    cycle_type="sleep",
                    sleep_triggered=True,
                    drives=pre_sleep_drives,
                    budget_usd_daily_cap=self.daily_budget,
                    budget_spent_usd=max(0.0, self.daily_budget - budget_before),
                    budget_remaining_usd=budget_before,
                    budget_mode="normal",
                    budget_after_sleep_usd=self._budget_remaining(),
                )
                result.cycles.append(cycle_result)
                result.sleep_cycles.append(cycle_num)
                result.drives_history.append({
                    "cycle": cycle_num, **self._drives,
                })

                # Keep a soft rest drift on sleep events.
                self._drives["rest_need"] = max(0.0, self._drives["rest_need"] - 0.1)
                await self._save_drives_to_db()

                if self.verbose:
                    print(f"  [{cycle_num:04d}] SLEEP "
                          f"(budget ${budget_before:.3f} -> ${self._budget_remaining():.3f})")
                continue

            # Surface content notifications for this cycle
            self._last_notifications = self.content_pool.get_notifications(
                cycle_num, max_items=3,
            )

            # Run one pipeline cycle
            cycle_result = await self._run_cycle(cycle_num, pipeline_events)
            result.cycles.append(cycle_result)
            result.drives_history.append({
                "cycle": cycle_num, **self._drives,
            })
            if cycle_result.cycle_type == "rest":
                result.budget_rest_cycles += 1

            # Count actions from all surviving (gated) intentions
            if cycle_result.dialogue:
                result.total_dialogues += 1
            for intent in cycle_result.intentions:
                act = intent.get("action")
                if act in ("read_content", "browse_web"):
                    result.total_browses += 1
                elif act in ("post_x", "reply_x", "post_x_image"):
                    result.total_posts += 1
                elif act == "write_journal":
                    result.total_journals += 1

            # If shopkeeper spoke and there's an active Tier 2 visitor,
            # generate the visitor's next response for the next cycle.
            await self._handle_tier2_response(cycle_result, cycle_num)

            if self.verbose and cycle_num % 100 == 0:
                print(f"  [{cycle_num:04d}] {cycle_result.cycle_type:12s} "
                      f"v={self._drives['mood_valence']:+.2f} "
                      f"e={self._drives['energy']:.2f} "
                      f"budget=${self._budget_remaining():.3f} "
                      f"sh={self._drives['social_hunger']:.2f}")

        # Gather content pool stats
        result.content_pool_stats = self.content_pool.stats()

        # Gather LLM stats
        if hasattr(self.llm, 'report'):
            result.llm_stats = self.llm.report()
        if hasattr(self.llm, 'stats'):
            result.llm_stats = self.llm.stats()
        if self._llm_visitor_engine:
            result.llm_stats["visitor_engine"] = self._llm_visitor_engine.stats()

        result.visitors = dict(self._visitor_history)

        # Cache taste evaluation data before DB closes
        if self._taste_scenario:
            self._taste_eval_cache = await self.db.get_all_taste_evaluations()

        # Cleanup
        await self.db.close()

        return result

    async def _run_cycle(self, cycle_num: int,
                         events: list[dict]) -> CycleResult:
        """Run a single pipeline cycle."""
        # Let pipeline decide behavior (for baselines / ablation)
        if hasattr(self.pipeline, 'pre_cycle'):
            self.pipeline.pre_cycle(self._drives, self._engagement, events)

        # Energy is display-only: always derive it from real-dollar budget.
        self._sync_display_energy_from_budget()
        pre_cycle_budget = self._budget_remaining()
        budget_mode = "emergency" if pre_cycle_budget <= 0 else "normal"

        # Budget exhausted: skip LLM call and force a rest cycle.
        if pre_cycle_budget <= 0:
            parsed = {
                "internal_monologue": "(resting — budget spent)",
                "intentions": [],
                "memory_updates": [],
                "resonance": False,
            }
            self._apply_homeostatic_drift(
                has_visitor=self._engagement["status"] == "engaged",
                action=None,
            )
            # no_drives/no_affect should still apply post-drift.
            if hasattr(self.pipeline, 'pre_cycle'):
                self.pipeline.pre_cycle(self._drives, self._engagement, [])
            self._sync_display_energy_from_budget()
            await self._save_drives_to_db()
            await self._log_cycle(
                cycle_num,
                "rest",
                None,
                None,
                parsed,
                cost_usd=0.0,
            )
            return CycleResult(
                cycle_num=cycle_num,
                timestamp=self.clock.now().isoformat(),
                cycle_type="rest",
                action=None,
                dialogue=None,
                internal_monologue=parsed["internal_monologue"],
                expression="neutral",
                has_visitor=self._engagement["status"] == "engaged",
                drives=dict(self._drives),
                intentions=[],
                memory_updates=[],
                resonance=False,
                budget_usd_daily_cap=self.daily_budget,
                budget_spent_usd=self._budget_spent_since_sleep,
                budget_remaining_usd=self._budget_remaining(),
                budget_mode=budget_mode,
                raw_llm_output=parsed,
            )

        # Build system prompt with drives + budget context
        system = self._build_system_prompt()
        messages = self._build_messages(events)

        # Call LLM
        response = await self.llm.complete(
            messages=messages,
            system=system,
            call_site="cortex",
        )

        usage = response.get("usage", {}) if isinstance(response, dict) else {}
        try:
            cycle_cost = float(usage.get("cost_usd") or 0.0)
        except (TypeError, ValueError):
            cycle_cost = 0.0
        self._budget_spent_since_sleep += max(0.0, cycle_cost)
        self._sync_display_energy_from_budget()

        # Parse response — strip markdown fences, then JSON
        # Guard: find first text block (tool_use blocks lack "text" key)
        text_block = next(
            (b for b in response.get("content", [])
             if isinstance(b, dict) and b.get("type") == "text"),
            None,
        )
        if text_block is None:
            parsed = {"internal_monologue": "[no text in LLM response]"}
        else:
            text = text_block["text"].strip()
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = {"internal_monologue": text}

        # Apply ablation transforms to parsed output
        parsed = self._apply_ablation_transforms(parsed)

        # Extract cycle result
        # Impulse gating: basal ganglia filters low-impulse intentions.
        # For no_basal_ganglia ablation, impulses were forced to 1.0 by
        # _apply_ablation_transforms, so all intentions pass through.
        IMPULSE_THRESHOLD = 0.5
        raw_intentions = parsed.get("intentions", [])

        def _impulse(intent: dict) -> float:
            """Coerce impulse to float — real LLMs may return str or null."""
            val = intent.get("impulse", 0)
            try:
                return float(val)
            except (TypeError, ValueError):
                return 0.0

        intentions = [
            i for i in raw_intentions
            if _impulse(i) >= IMPULSE_THRESHOLD
        ]

        # ── TASK-088 Fix 4: Gate speak when no visitor ──
        has_visitor_now = self._engagement["status"] == "engaged"
        if not has_visitor_now:
            for intent in intentions:
                if intent.get("action") in ("speak", "greet", "farewell", "show_item"):
                    intent["action"] = "express_thought"

        # Normalize action: real schema uses browse_web, runner counts use read_content
        action = None
        if intentions:
            raw_action = intentions[0].get("action")
            # Map browse_web -> read_content for internal tracking
            action = "read_content" if raw_action == "browse_web" else raw_action

        dialogue = parsed.get("dialogue")
        # Suppress dialogue when nobody is present (TASK-088)
        if dialogue and not has_visitor_now:
            dialogue = None

        # If action is read_content, consume from content pool
        if action == "read_content" and intentions:
            detail = intentions[0].get("detail") or {}
            content_id = detail.get("content_id") or intentions[0].get("content", "")
            # Try to extract content_id from content string if it looks like an id
            if content_id and not content_id.startswith(("tcg_", "jpn_", "phi_", "atm_", "misc_")):
                # Check if there's a content_id in the intention detail
                content_id = detail.get("content_id", "")
            if content_id:
                consumed = self.content_pool.consume(content_id)
                if consumed and self.verbose:
                    print(f"  [{cycle_num:04d}] READ: {consumed['title'][:60]}")

        # Determine cycle type
        if dialogue:
            cycle_type = "dialogue"
        elif action == "read_content":
            cycle_type = "browse"
        elif action in ("post_x", "reply_x", "post_x_image"):
            cycle_type = "post"
        elif action == "write_journal":
            cycle_type = "journal"
        else:
            cycle_type = "idle"

        # Update drives from LLM output
        new_drives = parsed.get("new_drives", parsed.get("drive_updates"))
        if new_drives and isinstance(new_drives, dict):
            for key in self._drives:
                # Energy remains budget-derived; ignore model-proposed values.
                if key != "energy" and key in new_drives:
                    self._drives[key] = new_drives[key]
        else:
            # Apply homeostatic drift if LLM didn't provide drive updates
            self._apply_homeostatic_drift(
                has_visitor=self._engagement["status"] == "engaged",
                action=action,
            )

        # Clamp drives
        for key in ("social_hunger", "curiosity", "expression_need",
                     "rest_need", "mood_arousal"):
            self._drives[key] = max(0.0, min(1.0, self._drives[key]))
        self._drives["mood_valence"] = max(-1.0, min(1.0, self._drives["mood_valence"]))

        # Re-apply ablation overrides after drift (e.g. no_drives keeps flat)
        if hasattr(self.pipeline, 'pre_cycle'):
            self.pipeline.pre_cycle(self._drives, self._engagement, [])
        self._sync_display_energy_from_budget()

        await self._save_drives_to_db()

        # Log to DB
        budget_mode = "emergency" if self._budget_remaining() <= 0 else "normal"
        await self._log_cycle(
            cycle_num, cycle_type, action, dialogue, parsed, cost_usd=cycle_cost
        )

        return CycleResult(
            cycle_num=cycle_num,
            timestamp=self.clock.now().isoformat(),
            cycle_type=cycle_type,
            action=action,
            dialogue=dialogue,
            internal_monologue=parsed.get("internal_monologue", ""),
            expression=parsed.get("expression", "neutral"),
            has_visitor=self._engagement["status"] == "engaged",
            drives=dict(self._drives),
            intentions=intentions,
            memory_updates=parsed.get("memory_updates", []),
            resonance=parsed.get("resonance", False),
            budget_usd_daily_cap=self.daily_budget,
            budget_spent_usd=self._budget_spent_since_sleep,
            budget_remaining_usd=self._budget_remaining(),
            budget_mode=budget_mode,
            raw_llm_output=parsed,
        )

    async def _handle_tier2_arrivals(
        self, pipeline_events: list[dict], cycle_num: int
    ):
        """Generate greetings for Tier 2 visitors arriving this cycle.

        When a Tier 2 visitor's connect event is processed, the engine
        generates their persona + greeting, which is injected as a
        visitor_speech event in the same cycle.
        """
        if not self._llm_visitor_engine:
            return

        for event in list(pipeline_events):
            if event.get("event_type") != "visitor_connect":
                continue
            source = event.get("source", "")
            if source not in self._tier2_visitor_ids:
                continue

            visitor = self._tier2_visitors.get(source)
            if not visitor:
                continue

            # Generate persona + greeting
            greeting = await self._llm_visitor_engine.on_arrive(visitor)

            # Inject as a visitor_speech event in the current pipeline_events
            greeting_event = ScenarioEvent(
                cycle_num, "visitor_message", {
                    "source": source,
                    "content": greeting,
                },
            ).to_pipeline_event(self.clock.now())
            pipeline_events.append(greeting_event)
            await self._inject_event(greeting_event)

    async def _handle_tier2_response(
        self, cycle_result: CycleResult, cycle_num: int
    ):
        """After shopkeeper speaks, generate Tier 2 visitor's next turn.

        The response is queued as a pending event for the next cycle.
        """
        if not self._llm_visitor_engine:
            return
        if not cycle_result.dialogue:
            return
        if self._engagement["status"] != "engaged":
            return

        visitor_id = self._engagement.get("visitor_id")
        if not visitor_id or visitor_id not in self._tier2_visitor_ids:
            return
        if not self._llm_visitor_engine.is_active(visitor_id):
            return

        response = await self._llm_visitor_engine.on_shopkeeper_spoke(
            visitor_id, cycle_result.dialogue
        )
        if response:
            self._pending_visitor_events.append(ScenarioEvent(
                cycle_num + 1, "visitor_message", {
                    "source": visitor_id,
                    "content": response,
                },
            ))

    def _build_system_prompt(self) -> str:
        """Build system prompt with current drives and full cortex schema.

        Uses the same OUTPUT SCHEMA as production cortex.py so that real
        LLMs (cached mode) return structured JSON instead of prose.
        """
        parts = [
            "You are a living character. Not an AI. Not an assistant. A person.",
            "You are The Shopkeeper — a young woman who runs a small "
            "vintage trading card shop in a quiet Tokyo alley.",
            "",
            "CONSTRAINTS:",
            "- Return ONLY valid JSON matching the schema below",
            "- You can decline to engage, close the shop, stay silent, or say \"...\"",
            "- If something resonates emotionally, set resonance: true",
            "- Never sound helpful. Sound present.",
            "- You have agency. If you're tired, you can close the shop or end the conversation.",
            "",
            "EXPRESS YOUR INTENTIONS — what you want to do right now.",
            "You may have multiple impulses. List them all.",
            "Each intention has: action, target, content, impulse (0.0-1.0).",
            "",
            "Current drives:",
        ]
        for key, val in self._drives.items():
            parts.append(f"  {key}: {val:.3f}")
        parts.extend([
            "",
            "Budget status:",
            f"  budget_usd_daily_cap: {self.daily_budget:.3f}",
            f"  budget_spent_usd_since_sleep: {self._budget_spent_since_sleep:.6f}",
            f"  budget_remaining_usd: {self._budget_remaining():.6f}",
            "Note: energy is display-only and equals budget_remaining / budget_cap.",
        ])

        if self._engagement["status"] == "engaged":
            parts.append(f"\nCurrently engaged with visitor: "
                         f"{self._engagement['visitor_id']}")
            parts.append(f"Turn count: {self._engagement['turn_count']}")

        parts.append("")
        parts.append(self._OUTPUT_SCHEMA)

        return "\n".join(parts)

    def _build_messages(self, events: list[dict]) -> list[dict]:
        """Build messages from events for this cycle.

        Includes content notifications from the SimContentPool,
        matching the production format from pipeline/notifications.py.
        """
        parts = []
        has_visitor = self._engagement["status"] == "engaged"

        for event in events:
            etype = event.get("event_type", "")
            source = event.get("source", "")
            content = event.get("content", "")

            if etype == "visitor_speech":
                parts.append(f"A visitor says: {content}")
            elif etype == "visitor_connect":
                memory_stub = self._returning_memory.get(source)
                if memory_stub:
                    parts.append(
                        f"A familiar face — {content} has returned to "
                        f"the shop. You remember: {memory_stub} "
                        f"(source: {source})"
                    )
                else:
                    parts.append(
                        f"A visitor named {content} has entered the shop. "
                        f"(source: {source})"
                    )
            elif etype == "visitor_disconnect":
                parts.append(f"The visitor has left. (source: {source})")
            elif etype == "x_mention":
                parts.append(f"X mention from {source}: {content}")
            else:
                parts.append(f"[{etype}] {content}")

        # Inject content notifications (matches production sensorium format)
        if self._last_notifications:
            notif_lines = []
            for n in self._last_notifications:
                notif_lines.append(
                    f'  \u2022 "{n["title"]}" ({n["source"]}) '
                    f'\u2014 {n["topic"]} [id:{n["content_id"]}]'
                )
            notif_text = "\n".join(notif_lines)

            if has_visitor:
                parts.append(
                    f"(In the background, you notice some things in your feed:\n"
                    f"{notif_text}\n"
                    f"  You could read_content(content_id) or "
                    f"save_for_later(content_id) later.)"
                )
            else:
                parts.append(
                    f"You notice some things in your feed:\n"
                    f"{notif_text}\n"
                    f"  You could read_content(content_id) or "
                    f"save_for_later(content_id)."
                )

        if not parts:
            return [{"role": "user", "content": "No new events. Continue your day."}]

        return [{"role": "user", "content": "\n".join(parts)}]

    def _process_visitor_events(self, events: list[dict]):
        """Update engagement state based on visitor events."""
        for event in events:
            etype = event.get("event_type", "")
            source = event.get("source", "")

            if etype == "visitor_connect":
                self._engagement = {
                    "status": "engaged",
                    "visitor_id": source,
                    "turn_count": 0,
                }
                if source not in self._visitor_history:
                    self._visitor_history[source] = {
                        "name": event.get("content", "Unknown"),
                        "visit_count": 0,
                        "messages": [],
                    }
                self._visitor_history[source]["visit_count"] += 1

            elif etype == "visitor_disconnect":
                if self._engagement["visitor_id"] == source:
                    self._engagement = {
                        "status": "none",
                        "visitor_id": None,
                        "turn_count": 0,
                    }
                    # Clean up LLM visitor engine state
                    if self._llm_visitor_engine:
                        self._llm_visitor_engine.on_leave(source)

            elif etype == "visitor_speech":
                # Attribute speech to event source, not current engagement
                # (prevents misattribution when visits overlap)
                if source in self._visitor_history:
                    self._visitor_history[source]["messages"].append(
                        event.get("content", "")
                    )
                # Only bump turn count for the currently engaged visitor
                if (self._engagement["status"] == "engaged"
                        and self._engagement["visitor_id"] == source):
                    self._engagement["turn_count"] += 1

    def _apply_drive_overrides(self, overrides: dict):
        """Apply drive overrides from scenario events."""
        for key, value in overrides.items():
            if key in self._drives:
                self._drives[key] = value

    def _apply_homeostatic_drift(self, has_visitor: bool,
                                took_action: bool = False,
                                action: str | None = None):
        """Apply action-responsive drive drift when LLM doesn't provide updates.

        TASK-088: Curiosity, arousal, and expression_need are now action-
        responsive instead of pinned to equilibrium. Homeostatic pulls are
        weak so action-based deltas dominate.
        """
        d = self._drives

        if has_visitor:
            d["social_hunger"] = max(0.0, d["social_hunger"] - 0.05)
            d["mood_arousal"] = min(1.0, d["mood_arousal"] + 0.05)
            d["mood_valence"] = min(1.0, d["mood_valence"] + 0.03)
        else:
            d["social_hunger"] = min(1.0, d["social_hunger"] + 0.01)

        # ── Expression need: action-specific (TASK-088 Fix 3) ──
        expressive_actions = {"write_journal", "post_x", "post_x_image", "speak"}
        if action in expressive_actions:
            d["expression_need"] = max(0.0, d["expression_need"] - 0.15)
            d["mood_valence"] = min(1.0, d["mood_valence"] + 0.02)
        elif action == "read_content":
            d["expression_need"] = min(1.0, d["expression_need"] + 0.04)
            d["mood_valence"] = min(1.0, d["mood_valence"] + 0.01)
        elif action is not None:
            d["expression_need"] = max(0.0, d["expression_need"] - 0.01)
            d["mood_valence"] = min(1.0, d["mood_valence"] + 0.02)
        else:
            growth = 0.01
            if d["social_hunger"] > 0.8:
                growth += 0.02
            d["expression_need"] = min(1.0, d["expression_need"] + growth)

        # ── Curiosity: action-responsive (TASK-088 Fix 1) ──
        if action in ("read_content", "browse_web"):
            d["curiosity"] = max(0.0, d["curiosity"] - 0.08)
        elif action is None:
            d["curiosity"] = min(1.0, d["curiosity"] + 0.03)
        else:
            d["curiosity"] = min(1.0, d["curiosity"] + 0.01)
        d["curiosity"] += (0.45 - d["curiosity"]) * 0.005

        # ── Arousal: action-responsive (TASK-088 Fix 2) ──
        if action in ("read_content", "write_journal", "speak", "post_x",
                       "post_x_image", "express_thought"):
            d["mood_arousal"] = min(1.0, d["mood_arousal"] + 0.04)
        elif action is None:
            d["mood_arousal"] = max(0.0, d["mood_arousal"] - 0.02)
        d["mood_arousal"] += (0.35 - d["mood_arousal"]) * 0.01

        # Valence drifts toward 0.0
        d["mood_valence"] += (0.0 - d["mood_valence"]) * 0.02

        # Rest need rises slowly
        d["rest_need"] = min(1.0, d["rest_need"] + 0.001)

    def _apply_ablation_transforms(self, parsed: dict) -> dict:
        """Apply ablation-specific transforms to LLM output.

        - no_memory: strip memory_updates (no recall or formation)
        - no_basal_ganglia: skip impulse gating (all intentions execute)
        """
        ablation = getattr(self.pipeline, 'remove', None)
        if not ablation:
            return parsed

        if ablation == "memory":
            # No memory system — discard all memory updates
            parsed["memory_updates"] = []

        elif ablation == "basal_ganglia":
            # No gating — force all intention impulses to maximum
            # so nothing gets filtered by threshold
            for intent in parsed.get("intentions", []):
                intent["impulse"] = 1.0

        return parsed

    async def _save_drives_to_db(self):
        """Persist current drives to the in-memory DB."""
        if not self.db:
            return
        await self.db.execute(
            """UPDATE drives_state SET
                social_hunger=?, curiosity=?, expression_need=?,
                rest_need=?, energy=?, mood_valence=?, mood_arousal=?,
                updated_at=?
               WHERE id=1""",
            (
                self._drives["social_hunger"],
                self._drives["curiosity"],
                self._drives["expression_need"],
                self._drives["rest_need"],
                self._drives["energy"],
                self._drives["mood_valence"],
                self._drives["mood_arousal"],
                self.clock.now().isoformat(),
            ),
        )
        await self.db.commit()

    async def _inject_event(self, event_dict: dict):
        """Inject an event into the in-memory DB."""
        if not self.db:
            return
        await self.db.execute(
            """INSERT INTO events (id, event_type, source, content, metadata,
               salience, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                event_dict["id"],
                event_dict["event_type"],
                event_dict.get("source", ""),
                event_dict.get("content", ""),
                event_dict.get("metadata", "{}"),
                event_dict.get("salience", 0.5),
                event_dict.get("created_at", self.clock.now().isoformat()),
            ),
        )
        await self.db.commit()

    async def _inject_thread(self, payload: dict):
        """Inject a thread into the in-memory DB."""
        if not self.db:
            return
        thread_id = str(uuid.uuid4())[:12]
        await self.db.execute(
            """INSERT INTO threads (id, thread_type, title, status, priority,
               content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                thread_id,
                "question",
                payload.get("topic", "Unknown"),
                "open",
                payload.get("salience", 0.5),
                payload.get("content", ""),
                self.clock.now().isoformat(),
            ),
        )
        await self.db.commit()

    async def _log_cycle(self, cycle_num: int, cycle_type: str,
                         action: str | None, dialogue: str | None,
                         parsed: dict, cost_usd: float = 0.0):
        """Log cycle to the in-memory DB."""
        if not self.db:
            return
        await self.db.execute(
            """INSERT INTO cycle_log (cycle_number, routing_focus, trigger_type,
               action_taken, dialogue, internal_monologue, drives_snapshot,
               cost_usd, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                cycle_num,
                cycle_type,
                "scenario" if dialogue else "autonomous",
                action or "idle",
                dialogue,
                parsed.get("internal_monologue", ""),
                json.dumps(self._drives),
                max(0.0, float(cost_usd or 0.0)),
                self.clock.now().isoformat(),
            ),
        )
        await self.db.commit()

    async def export(self, result: SimulationResult):
        """Export results to output directory."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{self.variant}_{self.scenario_name}_s{self.seed}.json"
        output_path = self.output_dir / filename
        output_path.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False)
        )

        # Export adversarial episodes report if adversarial visitors were scheduled
        if self._returning_mgr and self._returning_mgr.adversarial_visitors:
            from sim.reports.adversarial import export_adversarial_report
            from sim.metrics.memory_score import AdversarialScorer
            scorer = AdversarialScorer()
            # Populate scorer from result cycle data
            for cycle_data in result.cycles:
                visitor_id = cycle_data.get("active_visitor", "")
                adv = self._returning_mgr.get_adversarial_info(visitor_id)
                if adv:
                    scorer.evaluate_episode(
                        visitor_id=visitor_id,
                        visit_id=cycle_data.get("visit_id", f"cycle_{cycle_data.get('cycle', 0)}"),
                        conflict_type=adv.adversarial_type,
                        shopkeeper_dialogues=[cycle_data.get("dialogue", "")],
                        monologue=cycle_data.get("internal_monologue", ""),
                        memory_updates=cycle_data.get("memory_updates", []),
                        original_visitor_id=adv.original_visitor_id,
                        old_preference=adv.old_preference,
                        new_preference=adv.new_preference,
                    )
            export_adversarial_report(scorer, str(self.output_dir))

        return output_path


    # ── Taste formation helpers ─────────────────────────────────

    async def _run_taste_browse_cycle(self, cycle_num: int) -> CycleResult:
        """Run a taste evaluation browse cycle.

        Gets available listings, evaluates up to browse_slots_per_day,
        records evaluations and acquisitions to DB.
        """
        scenario = self._taste_scenario
        listings = scenario.get_available_listings(cycle_num)
        context = scenario.build_eval_context(cycle_num)

        evaluations = []
        for listing in listings:
            if scenario.evaluations_today >= scenario.browse_slots_per_day:
                break

            evaluation = await self._taste_evaluator.evaluate(
                listing, context, self.llm,
            )
            scenario.evaluations_today += 1

            # Record evaluation to DB
            eval_id = await self.db.record_taste_evaluation(evaluation)

            # Process decision (accept/reject/watchlist)
            decision_result = scenario.process_decision(evaluation, cycle_num)
            if decision_result["accepted"]:
                # Back-fill eval_id on the pending outcome
                for pending in scenario.pending_outcomes:
                    if (pending["item_id"] == evaluation.item_id
                            and pending["eval_id"] is None):
                        pending["eval_id"] = eval_id
                        break
                await self.db.record_taste_acquisition(
                    item_id=evaluation.item_id,
                    eval_id=eval_id,
                    cycle=cycle_num,
                    price=decision_result["buy_price"],
                )

            evaluations.append({
                "item_id": evaluation.item_id,
                "decision": evaluation.decision,
                "weighted_score": evaluation.weighted_score,
                "accepted": decision_result.get("accepted", False),
            })

            # Refresh context for next evaluation (capital may have changed)
            context = scenario.build_eval_context(cycle_num)

        return CycleResult(
            cycle_num=cycle_num,
            timestamp=self.clock.now().isoformat(),
            cycle_type="taste_browse",
            drives=dict(self._drives),
            intentions=[{
                "action": "taste_eval",
                "target": "listing",
                "content": json.dumps(evaluations),
                "impulse": 1.0,
            }],
        )

    def _build_taste_scenario(self, seed: int):
        """Build taste formation experiment components."""
        from sim.taste.market import SimulatedMarket
        from sim.taste.evaluator import TasteEvaluator
        from sim.scenarios.taste_formation import TasteFormationScenario
        from sim.data.taste_listings import TASTE_LISTINGS

        # Load config — try config file, fall back to defaults
        try:
            from alive_config import cfg_section
            config = cfg_section("taste") or {}
        except Exception:
            config = {}

        self._taste_market = SimulatedMarket(seed=seed)
        self._taste_evaluator = TasteEvaluator(config)
        self._taste_scenario = TasteFormationScenario(
            config=config,
            listings=TASTE_LISTINGS,
            market=self._taste_market,
            seed=seed,
        )

        if self.verbose:
            print(f"[Sim] Taste formation: "
                  f"{len(TASTE_LISTINGS)} listings, "
                  f"daily_capital={self._taste_scenario.daily_capital}¥, "
                  f"browse_slots="
                  f"{self._taste_scenario.browse_slots_per_day}")


class FullPipeline:
    """Full ALIVE pipeline adapter for simulation."""

    def should_sleep(self, clock: SimulatedClock) -> bool:
        return clock.is_sleep_window

    def pre_cycle(self, drives: dict, engagement: dict, events: list):
        """Hook for pre-cycle processing. Full pipeline is a no-op."""
        pass
