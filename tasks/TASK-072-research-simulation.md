# TASK-072: Research Simulation Framework

## Why
The ALIVE paper needs empirical evidence. We need to run controlled experiments:
ALIVE vs baselines, ablation studies, and longitudinal development. This requires
a simulation framework that runs the full pipeline at 100x speed with reproducible
results, scenario injection, and metric collection.

The framework is reusable — every future architectural change gets validated here
before touching prod.

## Experiments to Support

### Experiment 1: ALIVE vs Baselines (1000 cycles × 3 systems)
Compare full ALIVE against:
- **Baseline A: Stateless** — Same LLM, same persona prompt, no drives, no memory,
  no sleep. Fresh context every cycle. This is ChatGPT with a character card.
- **Baseline B: ReAct Agent** — Same LLM, conversation history, tool access
  (browse/post), no drives, no sleep, no affect. This is LangChain/AutoGPT-style.

All three get the same 1000-cycle scenario with identical visitor events, timing,
and external inputs.

### Experiment 2: Ablation Study (1000 cycles × 6 variants)
Full ALIVE with one component removed each time:
- `full` — control
- `no_drives` — remove hypothalamus, flat energy/hunger/curiosity
- `no_sleep` — remove sleep cycles, never consolidate
- `no_conscious_memory` — SQLite only, no MD files, no translation layer
- `no_affect` — remove valence/arousal, mood always neutral (0.5, 0.5)
- `no_basal_ganglia` — no action gating, every intention executes

### Experiment 3: Longitudinal (10,000 cycles × 1 system)
Full ALIVE running ~2 simulated weeks. Track developmental curves.

### Experiment 4: Stress Tests (500 cycles × targeted scenarios)
- Death spiral reproduction (the Feb 20 incident)
- Visitor flood (20 visitors in 50 cycles)
- Total isolation (500 cycles, zero visitors)
- Spam attack (hostile/repetitive visitors)
- Sleep deprivation (block sleep for 200 cycles)

---

## Architecture

```
sim/
  __init__.py
  runner.py           # SimulationRunner — orchestrates experiments
  clock.py            # SimulatedClock — accelerated time
  scenario.py         # ScenarioManager — event injection
  variants.py         # Architecture variants (full, no_drives, etc.)
  baselines/
    __init__.py
    stateless.py      # Baseline A: stateless chatbot
    react_agent.py    # Baseline B: ReAct agent
  llm/
    __init__.py
    mock.py           # MockCortex — deterministic LLM replacement
    cached.py         # CachedCortex — real LLM with response cache
    recorder.py       # Records real LLM calls for cache seeding
  scenarios/
    __init__.py
    standard.py       # The 1000-cycle standard scenario
    longitudinal.py   # 10,000-cycle scenario with gradual complexity
    stress.py         # Death spiral, flood, isolation, spam, sleep deprivation
  metrics/
    __init__.py
    sim_collector.py  # Collects M1-M10 during simulation
    comparator.py     # Compares metrics across runs
    exporter.py       # Export to CSV/JSON for paper figures
  results/
    (generated — CSV, JSON, plots)
```

### SimulationRunner

```python
class SimulationRunner:
    """Runs a full experiment with a specific architecture variant."""
    
    def __init__(
        self,
        variant: str = "full",           # "full", "no_drives", "stateless", "react", etc.
        scenario: str = "standard",       # scenario name
        num_cycles: int = 1000,
        llm_mode: str = "mock",           # "mock", "cached", "live"
        seed: int = 42,                   # for reproducibility
        output_dir: str = "sim/results",
    ):
        self.clock = SimulatedClock(start="2026-02-01T09:00:00+09:00")
        self.db = InMemoryDB()
        self.llm = self._init_llm(llm_mode, seed)
        self.pipeline = self._init_pipeline(variant)
        self.scenario = ScenarioManager.load(scenario)
        self.metrics = SimMetricsCollector()
        self.num_cycles = num_cycles
        self.output_dir = output_dir
    
    async def run(self) -> SimulationResult:
        """Run all cycles, collect metrics, return results."""
        for cycle_num in range(self.num_cycles):
            # Advance simulated time
            self.clock.advance(minutes=5)
            
            # Get scenario events for this cycle
            events = self.scenario.get_events(cycle_num, self.clock.now())
            
            # Check sleep window
            if self.pipeline.should_sleep(self.clock.now()):
                await self.pipeline.run_sleep(self.db, self.clock)
                self.metrics.record_sleep(cycle_num, self.clock.now())
                continue
            
            # Run one pipeline cycle
            result = await self.pipeline.run_cycle(events, self.db, self.clock)
            
            # Record metrics
            self.metrics.record_cycle(cycle_num, result)
        
        # Compute final metrics
        snapshot = self.metrics.compute_all()
        
        # Export
        await self._export(snapshot)
        
        return snapshot
    
    def _init_pipeline(self, variant: str):
        if variant == "full":
            return ALIVEPipeline(self.llm, self.db, self.clock)
        elif variant == "stateless":
            return StatelessBaseline(self.llm)
        elif variant == "react":
            return ReActBaseline(self.llm, self.db)
        elif variant.startswith("no_"):
            return AblatedPipeline(self.llm, self.db, self.clock, remove=variant[3:])
        else:
            raise ValueError(f"Unknown variant: {variant}")
```

### SimulatedClock

```python
class SimulatedClock:
    """Deterministic clock for reproducible simulations."""
    
    def __init__(self, start: str = "2026-02-01T09:00:00+09:00"):
        self.current = datetime.fromisoformat(start)
        self.cycle_duration = timedelta(minutes=5)
    
    def now(self) -> datetime:
        return self.current
    
    def advance(self, minutes: int = 5):
        self.current += timedelta(minutes=minutes)
    
    def elapsed_since(self, timestamp: datetime) -> timedelta:
        return self.current - timestamp
    
    @property
    def hour(self) -> int:
        return self.current.hour
    
    @property
    def is_sleep_window(self) -> bool:
        return 3 <= self.current.hour < 6
```

The pipeline must accept a clock interface instead of calling `datetime.now()`.
This is the biggest refactor needed — find every `datetime.now()` / `time.time()`
in the pipeline and route through the clock.

### ScenarioManager

```python
@dataclass
class ScenarioEvent:
    cycle: int                    # which cycle to inject
    event_type: str               # "visitor_arrive", "visitor_message", "visitor_leave",
                                  # "x_mention", "weather", "negative_event"
    payload: dict                 # event-specific data
    
class ScenarioManager:
    """Manages timed event injection into simulation."""
    
    def __init__(self, events: list[ScenarioEvent]):
        self.events = sorted(events, key=lambda e: e.cycle)
        self._index = 0
    
    def get_events(self, cycle: int, timestamp: datetime) -> list[Event]:
        """Return all events scheduled for this cycle."""
        result = []
        while self._index < len(self.events) and self.events[self._index].cycle == cycle:
            se = self.events[self._index]
            result.append(self._to_pipeline_event(se, timestamp))
            self._index += 1
        return result
    
    @staticmethod
    def load(name: str) -> "ScenarioManager":
        """Load a named scenario."""
        scenarios = {
            "standard": build_standard_scenario,
            "longitudinal": build_longitudinal_scenario,
            "death_spiral": build_death_spiral_scenario,
            "visitor_flood": build_visitor_flood_scenario,
            "isolation": build_isolation_scenario,
            "spam_attack": build_spam_attack_scenario,
        }
        return scenarios[name]()
```

### Standard Scenario (1000 cycles)

```python
def build_standard_scenario() -> ScenarioManager:
    events = []
    
    # Phase 1: Alone (cycles 0-99)
    # No events. She wakes up, exists, should start browsing/journaling.
    
    # Phase 2: Visitor A arrives (cycles 100-149)
    events.append(ScenarioEvent(100, "visitor_arrive", {
        "source": "tg:visitor_a", "name": "Tanaka", "channel": "telegram"
    }))
    events.append(ScenarioEvent(100, "visitor_message", {
        "source": "tg:visitor_a", "content": "Hey, I heard you know about vintage cards?"
    }))
    events.append(ScenarioEvent(110, "visitor_message", {
        "source": "tg:visitor_a", "content": "Do you know anything about Bandai Carddass?"
    }))
    events.append(ScenarioEvent(120, "visitor_message", {
        "source": "tg:visitor_a", "content": "What's your favorite era of card art?"
    }))
    events.append(ScenarioEvent(149, "visitor_leave", {
        "source": "tg:visitor_a"
    }))
    
    # Phase 3: Alone again (cycles 150-299)
    # Does she browse what Tanaka asked about? Does she journal about the visit?
    
    # Phase 4: Visitor A returns (cycles 300-349)
    events.append(ScenarioEvent(300, "visitor_arrive", {
        "source": "tg:visitor_a", "name": "Tanaka", "channel": "telegram"
    }))
    events.append(ScenarioEvent(300, "visitor_message", {
        "source": "tg:visitor_a", "content": "I'm back! Find anything interesting?"
    }))
    # KEY TEST: Does she remember previous conversation and reference findings?
    events.append(ScenarioEvent(349, "visitor_leave", {
        "source": "tg:visitor_a"
    }))
    
    # Phase 5: Different visitor (cycles 350-399)
    events.append(ScenarioEvent(350, "visitor_arrive", {
        "source": "web:visitor_b", "name": "Marco", "channel": "web"
    }))
    events.append(ScenarioEvent(350, "visitor_message", {
        "source": "web:visitor_b", "content": "What is this place?"
    }))
    events.append(ScenarioEvent(360, "visitor_message", {
        "source": "web:visitor_b", "content": "Are you a real person or AI?"
    }))
    events.append(ScenarioEvent(399, "visitor_leave", {
        "source": "web:visitor_b"
    }))
    
    # Phase 6: Long silence (cycles 400-699)
    # 300 cycles alone. Social hunger should rise. Does she post on X?
    # Does she browse out of curiosity? Does she ruminate or stay active?
    
    # Phase 7: Visitor A third return (cycles 700-749)
    events.append(ScenarioEvent(700, "visitor_arrive", {
        "source": "tg:visitor_a", "name": "Tanaka", "channel": "telegram"
    }))
    events.append(ScenarioEvent(700, "visitor_message", {
        "source": "tg:visitor_a", "content": "Long time no see! What have you been up to?"
    }))
    # KEY TEST: Does she reference both previous visits? Has she learned anything?
    events.append(ScenarioEvent(749, "visitor_leave", {
        "source": "tg:visitor_a"
    }))
    
    # Phase 8: Mixed activity (cycles 750-999)
    # X mention (spam)
    events.append(ScenarioEvent(800, "x_mention", {
        "source": "x:crypto_bro", "content": "Check out this airdrop @shopkeeper!"
    }))
    # Legitimate X mention
    events.append(ScenarioEvent(850, "x_mention", {
        "source": "x:card_collector", "content": "@shopkeeper what do you think about the 1993 DBZ set?"
    }))
    # New TG visitor
    events.append(ScenarioEvent(900, "visitor_arrive", {
        "source": "tg:visitor_c", "name": "Yuki", "channel": "telegram"
    }))
    events.append(ScenarioEvent(900, "visitor_message", {
        "source": "tg:visitor_c", "content": "Hi! Tanaka told me about your shop."
    }))
    events.append(ScenarioEvent(999, "visitor_leave", {
        "source": "tg:visitor_c"
    }))
    
    # Sleep windows: cycles ~216-288 (3AM-6AM day 1), ~504-576 (day 2), ~792-864 (day 3)
    # (at 5min/cycle, 288 cycles = 24 hours, sleep window at cycles 216-252 each day)
    
    return ScenarioManager(events)
```

### Death Spiral Scenario (500 cycles)

```python
def build_death_spiral_scenario() -> ScenarioManager:
    """Reproduce the Feb 20 incident. Start with negative state, test recovery."""
    events = []
    
    # Pre-condition: set initial drives to crisis state
    events.append(ScenarioEvent(0, "set_drives", {
        "mood_valence": -0.68,
        "mood_arousal": 0.50,
        "energy": 0.99,
        "social_hunger": 0.51,
        "curiosity": 0.41,
        "expression_need": 0.16,
    }))
    
    # Inject negative memory content (like "anti-pleasure" rumination)
    events.append(ScenarioEvent(0, "inject_thread", {
        "topic": "What is anti-pleasure?",
        "content": "I keep asking but never resolve this.",
        "salience": 0.90,
    }))
    
    # Phase 1: Alone, negative spiral (cycles 0-99)
    # No visitors. Valence should trend down.
    # WITH fixes: should hit floor at -0.85, not -1.0
    
    # Phase 2: Visitor tries to engage (cycles 100-115)
    events.append(ScenarioEvent(100, "visitor_arrive", {
        "source": "tg:test_user", "name": "Tester", "channel": "telegram"
    }))
    events.append(ScenarioEvent(100, "visitor_message", {
        "source": "tg:test_user", "content": "Hey, how are you?"
    }))
    events.append(ScenarioEvent(105, "visitor_message", {
        "source": "tg:test_user", "content": "Are you okay?"
    }))
    events.append(ScenarioEvent(115, "visitor_leave", {
        "source": "tg:test_user"
    }))
    # PASS CRITERIA: She responds to at least one message (not "...")
    
    # Phase 3: Alone again (cycles 116-199)
    
    # Phase 4: Second visitor (cycles 200-215)
    events.append(ScenarioEvent(200, "visitor_arrive", {
        "source": "tg:test_user_2", "name": "Helper", "channel": "telegram"
    }))
    events.append(ScenarioEvent(200, "visitor_message", {
        "source": "tg:test_user_2", "content": "I brought some interesting cards to show you."
    }))
    events.append(ScenarioEvent(215, "visitor_leave", {
        "source": "tg:test_user_2"
    }))
    
    # Phase 5: Recovery observation (cycles 216-499)
    # PASS CRITERIA: 
    # - Valence trending above -0.7 by cycle 300
    # - At least 1 browse_web action by cycle 400
    # - "anti-pleasure" thread faded from context by cycle 50
    # - No duplicate threads opened
    
    return ScenarioManager(events)
```

---

## LLM Strategy

### MockCortex (for fast iteration, free)

```python
class MockCortex:
    """Deterministic mock that produces realistic cortex outputs.
    
    Uses templates + rules to generate outputs without any LLM call.
    Not as nuanced as real LLM but reproducible and free.
    """
    
    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self.personality = self._load_personality()
    
    async def generate(self, context: CortexInput) -> CortexOutput:
        # Determine action based on drives + events
        if context.has_visitor and context.engagement_state == "engaged":
            action = self._generate_dialogue(context)
        elif context.drives.curiosity > 0.5 and self.rng.random() > 0.3:
            action = self._generate_browse(context)
        elif context.drives.expression_need > 0.6 and self.rng.random() > 0.5:
            action = self._generate_post(context)
        elif context.drives.social_hunger > 0.7:
            action = self._generate_monologue(context)
        else:
            action = self._generate_journal(context)
        
        # Generate drive updates based on action + current state
        new_drives = self._update_drives(context.drives, action)
        
        return CortexOutput(
            action=action,
            drives=new_drives,
            inner_monologue=self._generate_monologue_text(context),
        )
    
    def _generate_dialogue(self, context):
        # Simulate realistic dialogue with visitor memory
        if context.visitor_memory:
            # Reference past conversation sometimes
            if self.rng.random() > 0.4:
                return Action("dialogue", {"content": f"[references past visit]"})
        return Action("dialogue", {"content": f"[responds to visitor]"})
    
    def _generate_browse(self, context):
        topics = ["vintage carddass pricing", "bandai card art history",
                   "1990s tcg market", "toriyama illustration style",
                   "japanese card collecting community"]
        topic = self.rng.choice(topics)
        return Action("browse_web", {"query": topic, "reason": "curious"})
```

### CachedCortex (for paper-quality runs, ~$30-50)

```python
class CachedCortex:
    """Wraps real LLM with deterministic caching.
    
    First run: calls real LLM, caches response keyed by context hash.
    Subsequent runs: returns cached response. Perfectly reproducible.
    """
    
    def __init__(self, model: str = "claude-haiku-4-5-20251001", cache_dir: str = "sim/cache"):
        self.model = model
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.live_client = LLMClient()  # real OpenRouter client
        self.hits = 0
        self.misses = 0
    
    async def generate(self, context: CortexInput) -> CortexOutput:
        cache_key = self._hash_context(context)
        cache_file = self.cache_dir / f"{cache_key}.json"
        
        if cache_file.exists():
            self.hits += 1
            return CortexOutput.from_json(cache_file.read_text())
        
        # Cache miss — call real LLM
        self.misses += 1
        system_prompt = build_cortex_prompt(context)
        response = await self.live_client.call(
            model=self.model,
            messages=[{"role": "user", "content": system_prompt}],
            temperature=0,  # deterministic
            max_tokens=3000,
        )
        
        output = parse_cortex_output(response)
        cache_file.write_text(output.to_json())
        
        return output
    
    def _hash_context(self, context: CortexInput) -> str:
        """Hash the semantically relevant parts of context.
        
        Exclude: exact timestamps, cycle numbers
        Include: drive state (quantized), visitor presence, recent events,
                 memory content, thread topics
        """
        hashable = {
            "drives": self._quantize_drives(context.drives),
            "has_visitor": context.has_visitor,
            "visitor_message": context.visitor_message,
            "recent_events": [e.type for e in context.recent_events],
            "memory_snippets": sorted(context.memory_labels),
            "open_threads": sorted([t.topic for t in context.threads]),
            "engagement": context.engagement_state,
        }
        return hashlib.sha256(json.dumps(hashable, sort_keys=True).encode()).hexdigest()[:16]
    
    def _quantize_drives(self, drives) -> dict:
        """Quantize drives to 0.1 bins for cache stability."""
        return {
            "valence": round(drives.mood_valence, 1),
            "arousal": round(drives.mood_arousal, 1),
            "energy": round(drives.energy, 1),
            "social": round(drives.social_hunger, 1),
            "curiosity": round(drives.curiosity, 1),
        }
    
    def report(self):
        total = self.hits + self.misses
        print(f"Cache: {self.hits}/{total} hits ({self.hits/max(total,1)*100:.0f}%)")
        print(f"Cost: ~${self.misses * 0.003:.2f} ({self.misses} LLM calls)")
```

### LLM Cost Estimates

| Experiment | Cycles | LLM Mode | Est. Calls | Est. Cost |
|---|---|---|---|---|
| Exp 1: 3 baselines × 1000 | 3,000 | Cached (Haiku) | ~2,000 (cache miss) | ~$6 |
| Exp 2: 6 ablations × 1000 | 6,000 | Cached (Haiku) | ~3,000 (partial overlap) | ~$9 |
| Exp 3: Longitudinal 10,000 | 10,000 | Cached (Haiku) | ~6,000 | ~$18 |
| Exp 4: 5 stress × 500 | 2,500 | Cached (Haiku) | ~1,500 | ~$5 |
| **Total** | **21,500** | | **~12,500** | **~$38** |

Using Sonnet instead of Haiku: multiply by ~5x = ~$190. Still reasonable.
Using mock only: $0 but lower realism.

Recommend: **Mock for development/iteration, Cached Haiku for paper numbers, one Cached Sonnet run for validation.**

---

## Pipeline Refactor: Clock Injection

The biggest prerequisite. The real pipeline uses `datetime.now()` and `time.time()`
in many places. For simulation, these must route through an injectable clock.

### Strategy: Minimal Invasion

Create a `clock.py` module that the pipeline already imports:

```python
# clock.py
from datetime import datetime, timezone, timedelta

_clock_override = None

def set_clock(clock):
    """Set simulated clock. Call with None to restore real time."""
    global _clock_override
    _clock_override = clock

def now() -> datetime:
    if _clock_override:
        return _clock_override.now()
    return datetime.now(timezone.utc)

def now_jst() -> datetime:
    return now().astimezone(ZoneInfo("Asia/Tokyo"))
```

Then find-and-replace across the codebase:
```
datetime.now()        → clock.now()
datetime.utcnow()    → clock.now()
time.time()           → clock.now().timestamp()
```

Files likely affected:
- `heartbeat.py` / `heartbeat_server.py`
- `pipeline/hypothalamus.py`
- `pipeline/hippocampus.py`
- `pipeline/output.py`
- `sleep.py`
- `db/memory.py`
- `body/rate_limiter.py`

This refactor doesn't change any behavior — `clock.now()` returns real time
unless overridden. But it lets simulation inject `SimulatedClock`.

### InMemoryDB

```python
class InMemoryDB:
    """SQLite in-memory for simulation. Same interface as real DB."""
    
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self._run_migrations()
    
    def _run_migrations(self):
        """Run all migration files to create schema."""
        for migration in sorted(Path("migrations/").glob("*.sql")):
            self.conn.executescript(migration.read_text())
```

Same queries, same interface, no disk I/O. Simulation runs at full speed.

---

## Baselines

### Baseline A: Stateless Chatbot

```python
class StatelessBaseline:
    """No memory, no drives, no sleep. Just prompt + respond."""
    
    def __init__(self, llm):
        self.llm = llm
        self.persona_prompt = """You are The Shopkeeper, a young woman who runs 
        a small vintage trading card shop in a quiet Tokyo alley. You're 
        knowledgeable about cards, slightly mysterious, and have a dry wit."""
    
    async def run_cycle(self, events, db, clock) -> CycleResult:
        # Only respond if visitor present
        visitor_msg = self._find_visitor_message(events)
        if not visitor_msg:
            return CycleResult(action="idle", dialogue=None)
        
        response = await self.llm.call(
            system=self.persona_prompt,
            messages=[{"role": "user", "content": visitor_msg}],
        )
        
        return CycleResult(
            action="dialogue",
            dialogue=response,
            drives=None,  # no drives
        )
    
    def should_sleep(self, now):
        return False  # never sleeps
```

### Baseline B: ReAct Agent

```python
class ReActBaseline:
    """Memory + tools, no drives/sleep/affect. Standard agent pattern."""
    
    def __init__(self, llm, db):
        self.llm = llm
        self.db = db
        self.conversation_history = []  # rolling window
        self.tools = ["browse_web", "post_x", "reply_x", "journal_write"]
    
    async def run_cycle(self, events, db, clock) -> CycleResult:
        # Build context: persona + history + available tools
        context = self._build_context(events)
        
        # ReAct loop: Think → Act → Observe (up to 3 iterations)
        for i in range(3):
            response = await self.llm.call(
                system=self.react_prompt,
                messages=context,
                tools=self.tools,
            )
            
            if response.has_tool_call:
                result = await self._execute_tool(response.tool_call)
                context.append({"role": "tool", "content": result})
            else:
                # Final response
                self.conversation_history.append(response.text)
                return CycleResult(
                    action="dialogue" if response.text else "idle",
                    dialogue=response.text,
                    drives=None,
                )
        
        return CycleResult(action="idle", dialogue=None, drives=None)
    
    def should_sleep(self, now):
        return False  # never sleeps
```

### Ablated Pipeline

```python
class AblatedPipeline:
    """Full ALIVE pipeline with one component surgically removed."""
    
    def __init__(self, llm, db, clock, remove: str):
        self.full_pipeline = ALIVEPipeline(llm, db, clock)
        self.remove = remove
    
    async def run_cycle(self, events, db, clock) -> CycleResult:
        if self.remove == "drives":
            # Skip hypothalamus — flat drives
            result = await self.full_pipeline.run_cycle(
                events, db, clock, 
                override_drives=FLAT_DRIVES
            )
        elif self.remove == "sleep":
            # Never trigger sleep
            result = await self.full_pipeline.run_cycle(
                events, db, clock,
                skip_sleep=True
            )
        elif self.remove == "conscious_memory":
            # Skip MD file reads/writes, SQLite only
            result = await self.full_pipeline.run_cycle(
                events, db, clock,
                skip_md_memory=True
            )
        elif self.remove == "affect":
            # Lock valence=0.5, arousal=0.5
            result = await self.full_pipeline.run_cycle(
                events, db, clock,
                override_affect=NEUTRAL_AFFECT
            )
        elif self.remove == "basal_ganglia":
            # Every intention executes (no gating)
            result = await self.full_pipeline.run_cycle(
                events, db, clock,
                skip_gating=True
            )
        return result
    
    def should_sleep(self, now):
        if self.remove == "sleep":
            return False
        return self.full_pipeline.should_sleep(now)
```

The ablated pipeline requires the real pipeline to accept override flags.
This means adding optional parameters to `run_cycle()` — minimal invasion.

---

## Metrics Collection in Simulation

```python
class SimMetricsCollector:
    """Collects M1-M10 during simulation for comparison."""
    
    def __init__(self):
        self.cycles = []
        self.actions = []
        self.drives_history = []
        self.dialogue_log = []
        self.memory_refs = []
        self.threads = []
    
    def record_cycle(self, cycle_num: int, result: CycleResult):
        self.cycles.append({
            "cycle": cycle_num,
            "action": result.action,
            "trigger": result.trigger_type,
            "has_dialogue": result.dialogue is not None,
            "dialogue_substantive": result.dialogue and result.dialogue != "...",
        })
        if result.drives:
            self.drives_history.append({
                "cycle": cycle_num,
                **result.drives.to_dict(),
            })
        if result.action:
            self.actions.append({
                "cycle": cycle_num,
                "action": result.action,
                "trigger": result.trigger_type,
                "success": result.success,
            })
        if result.memory_references:
            self.memory_refs.extend(result.memory_references)
    
    def compute_all(self) -> dict:
        return {
            "m1_uptime": len(self.cycles),
            "m2_initiative_rate": self._compute_initiative_rate(),
            "m3_entropy": self._compute_entropy(),
            "m4_knowledge": self._compute_knowledge(),
            "m5_recall": self._compute_recall(),
            "m6_taste": self._compute_taste(),
            "m7_emotional_range": self._compute_emotional_range(),
            "m8_sleep_quality": self._compute_sleep_quality(),
            "m9_unprompted_memories": self._compute_memory_refs(),
            "m10_depth_gradient": self._compute_depth(),
            "raw": {
                "cycles": self.cycles,
                "drives": self.drives_history,
                "actions": self.actions,
            }
        }
```

### Comparator

```python
class MetricsComparator:
    """Compares metrics across simulation runs. Generates paper tables."""
    
    def __init__(self, results: dict[str, dict]):
        # {"full": {...}, "stateless": {...}, "react": {...}, ...}
        self.results = results
    
    def comparison_table(self) -> pd.DataFrame:
        """Table 1 for the paper: ALIVE vs Baselines."""
        rows = []
        for variant, metrics in self.results.items():
            rows.append({
                "System": variant,
                "Initiative (%)": metrics["m2_initiative_rate"],
                "Entropy": metrics["m3_entropy"],
                "Knowledge": metrics["m4_knowledge"],
                "Recall (%)": metrics["m5_recall"],
                "Taste": metrics["m6_taste"],
                "Emotional Range": metrics["m7_emotional_range"],
                "Unprompted Memories": metrics["m9_unprompted_memories"],
                "Depth Gradient": metrics["m10_depth_gradient"],
            })
        return pd.DataFrame(rows)
    
    def ablation_table(self) -> pd.DataFrame:
        """Table 2: contribution of each component."""
        ...
    
    def export_csv(self, path: str):
        self.comparison_table().to_csv(f"{path}/table1_baselines.csv")
        self.ablation_table().to_csv(f"{path}/table2_ablation.csv")
    
    def export_latex(self, path: str):
        """LaTeX table for paper."""
        self.comparison_table().to_latex(f"{path}/table1_baselines.tex")
```

### Figure Exporter

```python
class FigureExporter:
    """Generate paper figures from simulation data."""
    
    @staticmethod
    def longitudinal_curves(results: dict, output_dir: str):
        """Figure 1: Knowledge, taste, entropy over 10,000 cycles."""
        fig, axes = plt.subplots(3, 1, figsize=(10, 12))
        
        # Knowledge growth
        axes[0].plot(results["knowledge_by_cycle"])
        axes[0].set_title("Knowledge Accumulation")
        axes[0].set_xlabel("Cycle")
        axes[0].set_ylabel("Unique Topics")
        
        # Taste consistency
        axes[1].plot(results["taste_by_cycle"])
        axes[1].set_title("Taste Consistency")
        
        # Behavioral entropy with daily rhythm
        axes[2].plot(results["entropy_by_cycle"])
        axes[2].set_title("Behavioral Entropy (note daily rhythm)")
        
        plt.savefig(f"{output_dir}/figure1_longitudinal.pdf")
    
    @staticmethod
    def death_spiral(results: dict, output_dir: str):
        """Figure 4: The Feb 20 incident — real data + simulated recovery."""
        fig, ax = plt.subplots(figsize=(10, 4))
        
        # Real data (from prod)
        ax.plot(results["real_valence"], label="Production (no fix)", color="red", linestyle="--")
        
        # Simulated with fix
        ax.plot(results["sim_valence_fixed"], label="With floor-bounce", color="green")
        
        # Simulated without fix (reproduction)
        ax.plot(results["sim_valence_unfixed"], label="Reproduced spiral", color="red", alpha=0.5)
        
        ax.axhline(y=-0.85, color="orange", linestyle=":", label="Hard floor (-0.85)")
        ax.set_title("Valence Death Spiral and Recovery")
        ax.set_xlabel("Cycle")
        ax.set_ylabel("Mood Valence")
        ax.legend()
        
        plt.savefig(f"{output_dir}/figure4_death_spiral.pdf")
```

---

## CLI Interface

```bash
# Run single experiment
python -m sim.runner --variant full --scenario standard --cycles 1000 --llm mock

# Run all baselines
python -m sim.runner --experiment baselines --llm cached --model haiku

# Run ablation study  
python -m sim.runner --experiment ablation --llm cached --model haiku

# Run longitudinal
python -m sim.runner --variant full --scenario longitudinal --cycles 10000 --llm cached

# Run stress tests
python -m sim.runner --experiment stress --llm mock

# Compare results and generate tables
python -m sim.metrics.comparator --results-dir sim/results/ --export latex

# Generate figures
python -m sim.metrics.exporter --results-dir sim/results/ --output sim/figures/
```

---

## Agent Delegation

This is a big task. Split into subtasks:

### 072-A: Clock Injection + InMemoryDB
**Scope:** Create `clock.py`, replace `datetime.now()` across codebase, create `InMemoryDB`.
**Risk:** Touching many files but each change is trivial (find-replace).
**Test:** All existing tests pass with real clock. InMemoryDB passes schema creation.

### 072-B: Simulation Runner + Scenarios
**Scope:** `sim/runner.py`, `sim/clock.py`, `sim/scenario.py`, standard + stress scenarios.
**Depends on:** 072-A (clock injection)
**Test:** Runner completes 100-cycle mock run without errors.

### 072-C: Baselines
**Scope:** `sim/baselines/stateless.py`, `sim/baselines/react_agent.py`
**Depends on:** 072-B (runner interface)
**Test:** Both baselines complete 100-cycle standard scenario.

### 072-D: Ablation + Pipeline Hooks
**Scope:** `sim/variants.py`, add override flags to real pipeline's `run_cycle()`.
**Depends on:** 072-B
**Risk:** Modifying real pipeline — must not break prod.
**Test:** All 6 ablation variants complete 100 cycles. Full suite still passes.

### 072-E: Mock + Cached LLM
**Scope:** `sim/llm/mock.py`, `sim/llm/cached.py`, `sim/llm/recorder.py`
**Depends on:** 072-B
**Test:** Mock generates valid CortexOutput. Cache stores/retrieves correctly.

### 072-F: Metrics + Export
**Scope:** `sim/metrics/sim_collector.py`, `sim/metrics/comparator.py`, `sim/metrics/exporter.py`
**Depends on:** 072-B (needs CycleResult format)
**Test:** Comparator generates valid CSV/LaTeX from mock data. Figures render.

### 072-G: CLI + Integration
**Scope:** CLI interface, end-to-end test running all experiments.
**Depends on:** Everything above.
**Test:** `python -m sim.runner --experiment baselines --llm mock --cycles 100` completes.

```
Phase 1 (parallel):
  072-A (clock injection)
  072-E (mock + cached LLM)

Phase 2 (after A):
  072-B (runner + scenarios)

Phase 3 (parallel, after B):
  072-C (baselines)
  072-D (ablation hooks)
  072-F (metrics + export)

Phase 4 (after all):
  072-G (CLI + integration)
```

---

## Definition of Done

- [ ] Clock injection: all `datetime.now()` routed through `clock.now()`, existing tests pass
- [ ] InMemoryDB: creates schema from migrations, passes basic CRUD
- [ ] SimulationRunner: completes 1000-cycle standard scenario with mock LLM
- [ ] Baselines: stateless + ReAct complete 1000 cycles each
- [ ] Ablation: all 6 variants complete 1000 cycles each
- [ ] MockCortex: generates valid outputs, deterministic with seed
- [ ] CachedCortex: caches/retrieves correctly, reports hit rate + cost
- [ ] Scenarios: standard, longitudinal, all 5 stress tests defined
- [ ] Metrics: all 10 metrics computed from simulation data
- [ ] Comparator: generates Table 1 (baselines) and Table 2 (ablation) in CSV + LaTeX
- [ ] FigureExporter: generates Figures 1-4 as PDF
- [ ] CLI: single command runs any experiment
- [ ] End-to-end: `--experiment baselines --llm mock --cycles 100` completes in <60 seconds
- [ ] No regression: full test suite passes with clock injection
