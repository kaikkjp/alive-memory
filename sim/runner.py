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
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sim.clock import SimulatedClock
from sim.db import InMemoryDB
from sim.scenario import ScenarioManager


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
      "action": "speak|write_journal|rearrange|express_thought|end_engagement|accept_gift|decline_gift|show_item|post_x_draft|open_shop|close_shop|place_item|browse_web|post_x|reply_x|post_x_image|tg_send|tg_send_image",
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

        # Initialize components
        self.clock = SimulatedClock(start=start_time)
        self.db: InMemoryDB | None = None
        self.llm = self._init_llm(llm_mode, seed)
        self.pipeline = self._init_pipeline(variant)
        self.scenario = ScenarioManager.load(scenario)

        # Runtime state
        self._drives = {
            "social_hunger": 0.5,
            "curiosity": 0.5,
            "expression_need": 0.3,
            "rest_need": 0.2,
            "energy": 0.8,
            "mood_valence": 0.0,
            "mood_arousal": 0.3,
        }
        self._engagement = {
            "status": "none",
            "visitor_id": None,
            "turn_count": 0,
        }
        self._visitor_history: dict[str, dict] = {}  # visitor_id -> info

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
        )

        for cycle_num in range(self.num_cycles):
            # Advance simulated time
            self.clock.advance(minutes=5)

            # Get scenario events for this cycle
            scenario_events = self.scenario.get_events(cycle_num)

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

            # Handle visitor state from events
            self._process_visitor_events(pipeline_events)

            # Check sleep window
            if not self.block_sleep and self.pipeline.should_sleep(self.clock):
                cycle_result = CycleResult(
                    cycle_num=cycle_num,
                    timestamp=self.clock.now().isoformat(),
                    cycle_type="sleep",
                    sleep_triggered=True,
                    drives=dict(self._drives),
                )
                result.cycles.append(cycle_result)
                result.sleep_cycles.append(cycle_num)
                result.drives_history.append({
                    "cycle": cycle_num, **self._drives,
                })

                # Sleep restores energy
                self._drives["energy"] = min(1.0, self._drives["energy"] + 0.1)
                self._drives["rest_need"] = max(0.0, self._drives["rest_need"] - 0.1)
                await self._save_drives_to_db()

                if self.verbose:
                    print(f"  [{cycle_num:04d}] SLEEP "
                          f"(energy={self._drives['energy']:.2f})")
                continue

            # Run one pipeline cycle
            cycle_result = await self._run_cycle(cycle_num, pipeline_events)
            result.cycles.append(cycle_result)
            result.drives_history.append({
                "cycle": cycle_num, **self._drives,
            })

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

            if self.verbose and cycle_num % 100 == 0:
                print(f"  [{cycle_num:04d}] {cycle_result.cycle_type:12s} "
                      f"v={self._drives['mood_valence']:+.2f} "
                      f"e={self._drives['energy']:.2f} "
                      f"sh={self._drives['social_hunger']:.2f}")

        # Gather LLM stats
        if hasattr(self.llm, 'report'):
            result.llm_stats = self.llm.report()
        if hasattr(self.llm, 'stats'):
            result.llm_stats = self.llm.stats()

        result.visitors = dict(self._visitor_history)

        # Cleanup
        await self.db.close()

        return result

    async def _run_cycle(self, cycle_num: int,
                         events: list[dict]) -> CycleResult:
        """Run a single pipeline cycle."""
        # Build system prompt with drives
        system = self._build_system_prompt()

        # Build messages with events
        messages = self._build_messages(events)

        # Determine call site
        call_site = "cortex"

        # Let pipeline decide behavior (for baselines / ablation)
        if hasattr(self.pipeline, 'pre_cycle'):
            self.pipeline.pre_cycle(self._drives, self._engagement, events)

        # Call LLM
        response = await self.llm.complete(
            messages=messages,
            system=system,
            call_site=call_site,
        )

        # Parse response — strip markdown fences, then JSON
        text = response["content"][0]["text"].strip()
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

        # Normalize action: real schema uses browse_web, runner counts use read_content
        action = None
        if intentions:
            raw_action = intentions[0].get("action")
            # Map browse_web -> read_content for internal tracking
            action = "read_content" if raw_action == "browse_web" else raw_action

        dialogue = parsed.get("dialogue")

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
                if key in new_drives:
                    self._drives[key] = new_drives[key]
        else:
            # Apply homeostatic drift if LLM didn't provide drive updates
            self._apply_homeostatic_drift(
                has_visitor=self._engagement["status"] == "engaged",
                took_action=bool(action),
            )

        # Clamp drives
        for key in ("social_hunger", "curiosity", "expression_need",
                     "rest_need", "energy", "mood_arousal"):
            self._drives[key] = max(0.0, min(1.0, self._drives[key]))
        self._drives["mood_valence"] = max(-1.0, min(1.0, self._drives["mood_valence"]))

        # Re-apply ablation overrides after drift (e.g. no_drives keeps flat)
        if hasattr(self.pipeline, 'pre_cycle'):
            self.pipeline.pre_cycle(self._drives, self._engagement, [])

        await self._save_drives_to_db()

        # Log to DB
        await self._log_cycle(cycle_num, cycle_type, action, dialogue, parsed)

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
            raw_llm_output=parsed,
        )

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

        if self._engagement["status"] == "engaged":
            parts.append(f"\nCurrently engaged with visitor: "
                         f"{self._engagement['visitor_id']}")
            parts.append(f"Turn count: {self._engagement['turn_count']}")

        parts.append("")
        parts.append(self._OUTPUT_SCHEMA)

        return "\n".join(parts)

    def _build_messages(self, events: list[dict]) -> list[dict]:
        """Build messages from events for this cycle."""
        if not events:
            return [{"role": "user", "content": "No new events. Continue your day."}]

        parts = []
        for event in events:
            etype = event.get("event_type", "")
            source = event.get("source", "")
            content = event.get("content", "")

            if etype == "visitor_speech":
                parts.append(f"A visitor says: {content}")
            elif etype == "visitor_connect":
                parts.append(f"A visitor named {content} has entered the shop. "
                             f"(source: {source})")
            elif etype == "visitor_disconnect":
                parts.append(f"The visitor has left. (source: {source})")
            elif etype == "x_mention":
                parts.append(f"X mention from {source}: {content}")
            else:
                parts.append(f"[{etype}] {content}")

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

            elif etype == "visitor_speech":
                if self._engagement["status"] == "engaged":
                    self._engagement["turn_count"] += 1
                    vid = self._engagement["visitor_id"]
                    if vid and vid in self._visitor_history:
                        self._visitor_history[vid]["messages"].append(
                            event.get("content", "")
                        )

    def _apply_drive_overrides(self, overrides: dict):
        """Apply drive overrides from scenario events."""
        for key, value in overrides.items():
            if key in self._drives:
                self._drives[key] = value

    def _apply_homeostatic_drift(self, has_visitor: bool, took_action: bool):
        """Apply gentle drive drift when LLM doesn't provide updates."""
        d = self._drives

        if has_visitor:
            d["social_hunger"] = max(0.0, d["social_hunger"] - 0.05)
            d["mood_arousal"] = min(1.0, d["mood_arousal"] + 0.05)
            d["mood_valence"] = min(1.0, d["mood_valence"] + 0.03)
        else:
            d["social_hunger"] = min(1.0, d["social_hunger"] + 0.01)

        if took_action:
            d["expression_need"] = max(0.0, d["expression_need"] - 0.03)
            d["energy"] = max(0.0, d["energy"] - 0.02)
            d["mood_valence"] = min(1.0, d["mood_valence"] + 0.02)
        else:
            d["expression_need"] = min(1.0, d["expression_need"] + 0.005)

        # Curiosity drifts toward 0.5
        d["curiosity"] += (0.5 - d["curiosity"]) * 0.02

        # Arousal decays toward 0.3
        d["mood_arousal"] += (0.3 - d["mood_arousal"]) * 0.05

        # Valence drifts toward 0.0
        d["mood_valence"] += (0.0 - d["mood_valence"]) * 0.02

        # Energy slowly drains
        d["energy"] = max(0.0, d["energy"] - 0.002)

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
                         parsed: dict):
        """Log cycle to the in-memory DB."""
        if not self.db:
            return
        await self.db.execute(
            """INSERT INTO cycle_log (cycle_number, routing_focus, trigger_type,
               action_taken, dialogue, internal_monologue, drives_snapshot,
               timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                cycle_num,
                cycle_type,
                "scenario" if dialogue else "autonomous",
                action or "idle",
                dialogue,
                parsed.get("internal_monologue", ""),
                json.dumps(self._drives),
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
        return output_path


class FullPipeline:
    """Full ALIVE pipeline adapter for simulation."""

    def should_sleep(self, clock: SimulatedClock) -> bool:
        return clock.is_sleep_window

    def pre_cycle(self, drives: dict, engagement: dict, events: list):
        """Hook for pre-cycle processing. Full pipeline is a no-op."""
        pass
