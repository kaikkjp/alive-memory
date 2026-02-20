# SIMULATION MODE — Architecture Spec

## For: Claude Code
## Goal: Run days/weeks of autonomous life in minutes, observe identity formation, tune feeds before going live
## Prereq: Living Loop (feat/living-loop) merged

---

## DESIGN PRINCIPLES

Time is the only difference between simulation and production. The pipeline, arbiter, Cortex, threads, content pool — everything runs identically. The only changes:

1. A virtual clock replaces `datetime.now()`
2. Sleep calls advance the clock instead of waiting
3. Weather is deterministic instead of fetched
4. Visitors are absent (pure autonomous life)
5. A timeline log prints compressed output

**Not a mock. Not a test harness.** She runs the real pipeline with real LLM calls. The simulation produces real journal entries, real totems, real threads, real collection items — all in a separate DB so production data isn't touched.

---

## 1. VIRTUAL CLOCK

**File:** `clock.py`

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

JST = ZoneInfo('Asia/Tokyo')

class Clock:
    """Drop-in time source. Real time in production, virtual in simulation."""
    
    def __init__(self, simulate: bool = False, 
                 start: datetime = None,
                 speed: float = 1.0):
        self._simulate = simulate
        self._speed = speed
        # Default start: 7:00 AM JST today (she wakes up)
        self._virtual_now = start or datetime.now(JST).replace(
            hour=7, minute=0, second=0, microsecond=0
        )
    
    def now(self) -> datetime:
        if self._simulate:
            return self._virtual_now
        return datetime.now(JST)
    
    def now_utc(self) -> datetime:
        if self._simulate:
            return self._virtual_now.astimezone(ZoneInfo('UTC'))
        return datetime.now(ZoneInfo('UTC'))
    
    def advance(self, seconds: float):
        """In simulate mode, jump forward. In production, no-op."""
        if self._simulate:
            self._virtual_now += timedelta(seconds=seconds)
    
    @property
    def is_simulating(self) -> bool:
        return self._simulate

# Module-level singleton, set once at startup
_clock = Clock()

def init_clock(simulate=False, start=None, speed=1.0):
    global _clock
    _clock = Clock(simulate=simulate, start=start, speed=speed)

def now() -> datetime:
    return _clock.now()

def now_utc() -> datetime:
    return _clock.now_utc()

def advance(seconds: float):
    _clock.advance(seconds)

def is_simulating() -> bool:
    return _clock.is_simulating
```

### Integration: Replace all time calls

Every file that calls `datetime.now()` switches to `clock.now()`:

```python
# Before:
from datetime import datetime, timezone
ts = datetime.now(timezone.utc)

# After:
import clock
ts = clock.now_utc()
```

Files that need this change (grep for `datetime.now`):
- `heartbeat.py`
- `heartbeat_server.py`
- `pipeline/arbiter.py`
- `pipeline/cortex.py` (circuit breaker timestamps)
- `pipeline/sensorium.py`
- `pipeline/executor.py`
- `pipeline/hippocampus_write.py`
- `sleep.py`
- `db.py`

This is mechanical — find/replace with one rule: always use `clock.now()` for JST, `clock.now_utc()` for UTC.

**Production is unaffected.** Without `init_clock(simulate=True)`, the module-level `_clock` is a real-time clock. All existing behavior unchanged.

---

## 2. SLEEP BECOMES CLOCK ADVANCE

**In `heartbeat.py`:**

```python
# Before:
await self._interruptible_sleep(random.randint(120, 600))

# After:
if clock.is_simulating():
    clock.advance(random.randint(120, 600))
else:
    await self._interruptible_sleep(random.randint(120, 600))
```

In simulation, every "wait" is instant — the clock just jumps forward. Cycle cadence, cooldowns, TTL expiry, sleep cycle triggers all work correctly because they compare against `clock.now()`.

**Sleep cycle trigger** still fires when simulated time crosses 03:00 JST. The check in `heartbeat.py` (already time-based) just sees the virtual clock hit 3 AM and runs the sleep cycle normally.

---

## 3. DETERMINISTIC WEATHER

In simulation, don't call wttr.in. Use a rotating weather pattern:

**File:** `pipeline/ambient.py` — add simulation path:

```python
import clock

SIMULATED_WEATHER_CYCLE = [
    # Each entry: (hour_range, condition, temp_c, humidity, diegetic, drive_nudges)
    ((6, 10),   'clear_cold',  5,  45, "Clear and cold. The light is sharp today.", {'mood_arousal': 0.05}),
    ((10, 14),  'overcast',    9,  60, "Grey sky. The kind of day that makes you want tea.", {}),
    ((14, 18),  'rain',        8,  80, "Rain on the windows. The sound fills the shop.", {'mood_valence': -0.05}),
    ((18, 22),  'clear_cold',  4,  50, "The cold has teeth tonight.", {'energy': -0.03}),
    ((22, 6),   'clear_cold',  2,  40, "Deep night. Still.", {}),
]

# Day-level variation: rotate through these modifiers
DAY_VARIATIONS = [
    {},                                          # Day 1: baseline
    {'condition': 'snow', 'diegetic': 'Snow. Everything outside is quiet.', 'drive_nudges': {'mood_valence': 0.05}},  # Day 2: snow
    {},                                          # Day 3: baseline
    {'condition': 'heavy_rain', 'diegetic': "It's pouring. No one will come today.", 'drive_nudges': {'mood_valence': -0.1, 'social_hunger': 0.05}},  # Day 4: storm
    {},                                          # Day 5: baseline
    {'condition': 'hot', 'diegetic': 'Unusually warm for the season. The shop feels thick.', 'drive_nudges': {'energy': -0.03}},  # Day 6: warm
    {},                                          # Day 7: baseline
]

async def fetch_ambient_context(location: dict) -> dict:
    if clock.is_simulating():
        return _simulated_weather(clock.now())
    # ... existing wttr.in fetch ...
```

This gives her weather variety without network calls. Day 2 she gets snow, Day 4 a storm — enough variation to produce different moods and journal entries.

---

## 4. SEPARATE DATABASE

Simulation writes to a separate DB so production data is never touched:

```bash
# Production (default):
data/shopkeeper.db

# Simulation:
data/sim/sim_YYYYMMDD_HHMMSS.db
```

The simulation entrypoint creates a fresh DB with all migrations applied, then ingests the content pool before starting.

```python
# In simulate.py:
sim_db_path = f"data/sim/sim_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
os.makedirs("data/sim", exist_ok=True)
os.environ['SHOPKEEPER_DB_PATH'] = sim_db_path

# Init fresh DB with migrations
await init_db()

# Pre-load content pool
await ingest_file('content/readings.txt')
# Optional: ingest from RSS snapshot
await ingest_file('content/rss_snapshot.txt')
```

After simulation, the DB persists. You can inspect it with `sqlite3` to examine journal entries, threads, totems, collection — the full record of her simulated life.

---

## 5. CONTENT PRELOADING

RSS feeds can't be sped up — they return real-time content. Two solutions:

### Option A: Snapshot file (simple, recommended)

Before simulation, capture current RSS content:

```bash
# New command in ingest.py:
python ingest.py --snapshot-feeds

# Fetches all configured RSS feeds once, saves entries to content/rss_snapshot.txt
# One URL/headline per line, with tags
# This file gets bulk-ingested at simulation start
```

### Option B: Staggered drip (more realistic)

Instead of loading everything at once, the simulation drip-feeds pool items as the virtual clock advances:

```python
# Pre-assign each pool item a simulated_available_at timestamp
# Spread across the simulation window
# Pool queries filter: WHERE simulated_available_at <= clock.now()
```

This simulates "new content arriving over the week" instead of everything being available on Day 1.

**Recommendation:** Start with Option A. It's simpler and good enough for tuning. Option B is a refinement if you want more realistic flow dynamics.

### Pool sizing

For a 7-day simulation at 3 consumes/day max = 21 consumption cycles. Add news and idle encounters, she might look at ~50-70 items total. Load at least 100 pool items so she has choices and some get ignored (that's signal too).

Sources:
- `content/feb10-readings.txt` (already exists)
- RSS snapshot from the 8 configured feeds
- Optional: a hand-curated `content/simulation-extras.txt` with URLs you want to test

---

## 6. NO VISITORS

Simulation runs pure autonomous life. The engagement FSM stays in `none` state. No TCP server, no terminal listener.

This is the simplest path — just don't start `heartbeat_server.py`. Run the heartbeat loop directly.

Future enhancement: simulated visitors at scripted times. Not needed for first simulation.

---

## 7. TIMELINE LOG

**File:** `timeline.py`

A compact, human-readable log of what she does. Prints to stdout and writes to `data/sim/timeline_YYYYMMDD_HHMMSS.log`.

```python
class TimelineLogger:
    def __init__(self, log_path: str):
        self._f = open(log_path, 'w')
    
    def log_cycle(self, sim_time: datetime, focus_channel: str, 
                  detail: str, actions: list[str]):
        day = (sim_time - self._start).days + 1
        time_str = sim_time.strftime('%H:%M')
        
        line = f"[Day {day}  {time_str}] {focus_channel.upper()}"
        if detail:
            line += f" — {detail}"
        print(line)
        self._f.write(line + '\n')
        
        for action in actions:
            action_line = f"               → {action}"
            print(action_line)
            self._f.write(action_line + '\n')
    
    def log_sleep(self, sim_time: datetime, digest: dict):
        day = (sim_time - self._start).days + 1
        threads = digest.get('active_threads', {})
        line = f"[Day {day}  03:00] SLEEP — threads: {threads.get('active', 0)} active, {threads.get('dormant', 0)} dormant, {threads.get('closed', 0)} closed"
        print(line)
        self._f.write(line + '\n')
    
    def log_wake(self, sim_time: datetime, threads: list):
        day = (sim_time - self._start).days + 1
        carries = ', '.join(f'"{t.title}"' for t in threads[:3])
        line = f"[Day {day}  07:00] WAKE — carries: {carries}"
        print(line)
        self._f.write(line + '\n')
```

### Example output:

```
[Day 1  07:00] WAKE — carries: (none)
[Day 1  07:15] IDLE — weather: clear, cold. "Sharp light today."
[Day 1  08:30] CONSUME — "The Difficult Art of Giving" (themarginalian.org)
               → journal_entry
               → totem_create("giving as loss")
[Day 1  10:45] THREAD_CREATE — "Why does generosity feel like grief?" [question]
[Day 1  13:00] NEWS — "Kintsugi artist repairs public benches" (spoon-tamago.com)
               → thread_update("generosity/grief") — touch_reason: "repair as gift"
[Day 1  15:20] IDLE — weather: rain. "Rain on the windows."
[Day 1  17:00] CONSUME — "Echoes in Empty Stations" (lensculture.com)
               → collection_add(backroom)
               → thread_create("liminal spaces")
[Day 1  19:30] EXPRESS — journal about rain and waiting
[Day 1  21:00] IDLE — weather: cold night.
[Day 2  03:00] SLEEP — threads: 2 active, 0 dormant, 0 closed. Totems: 2. Collection: 1.
               Journal: "Today I learned that giving things away..."
[Day 2  07:00] WAKE — carries: "generosity/grief", "liminal spaces"
[Day 2  08:00] THREAD — "liminal spaces" — thinking about the backroom photo
               → thread_update — "the station photo feels like it belongs near the door"
...
[Day 7  03:00] SLEEP — threads: 4 active, 3 dormant, 2 closed. Totems: 11. Collection: 8.
               Journal: "This week I kept returning to the idea of..."

=== SIMULATION COMPLETE: 7 days, 89 cycles, 19 consumes, 4.2s avg/cycle ===
```

### Extracting actions from cycle results

After each cycle's executor runs, the timeline logger inspects the cycle result for:
- `journal_entry` in memory_updates → log it
- `totem_create` → log name
- `collection_add` → log placement
- `thread_create/update/close` → log title and reason
- `post_x_draft` → log draft summary
- Arbiter focus channel + payload title → log as primary line

This is read-only — it just inspects what the executor already did.

---

## 8. SIMULATION ENTRYPOINT

**File:** `simulate.py`

```bash
# Basic: simulate 7 days
python simulate.py --days 7

# Custom start time
python simulate.py --days 3 --start "2025-02-10T07:00:00+09:00"

# With specific content file
python simulate.py --days 7 --content content/readings.txt content/rss_snapshot.txt

# Snapshot feeds first, then simulate
python simulate.py --days 7 --snapshot-feeds

# Quiet mode (timeline log only, no per-cycle debug output)
python simulate.py --days 7 --quiet
```

### Main loop:

```python
async def run_simulation(days: int, content_files: list[str], start: datetime = None):
    # 1. Init virtual clock
    init_clock(simulate=True, start=start)
    
    # 2. Create fresh sim DB
    sim_id = clock.now().strftime('%Y%m%d_%H%M%S')
    sim_db = f"data/sim/sim_{sim_id}.db"
    os.environ['SHOPKEEPER_DB_PATH'] = sim_db
    await init_db()
    
    # 3. Pre-load content pool
    for f in content_files:
        await ingest_file(f)
    pool_count = await db.get_pool_count(status='unseen')
    print(f"Pool loaded: {pool_count} items")
    
    # 4. Init timeline logger
    log_path = f"data/sim/timeline_{sim_id}.log"
    timeline = TimelineLogger(log_path)
    
    # 5. Create heartbeat (no server, no terminal)
    heartbeat = Heartbeat(clock=_clock, timeline=timeline)
    
    # 6. Run until simulated time exceeds target
    target = clock.now() + timedelta(days=days)
    cycle_count = 0
    
    while clock.now() < target:
        # Run one autonomous cycle
        result = await heartbeat.run_one_cycle()
        cycle_count += 1
        
        # Log to timeline
        timeline.log_cycle(clock.now(), result.focus_channel, 
                          result.detail, result.actions)
        
        # Advance clock by the sleep duration the cycle would have waited
        clock.advance(result.sleep_seconds)
        
        # Check for sleep cycle trigger
        if heartbeat.should_sleep(clock.now()):
            digest = await heartbeat.run_sleep_cycle()
            timeline.log_sleep(clock.now(), digest)
            clock.advance(3 * 3600)  # skip 03:00-06:00
            timeline.log_wake(clock.now(), 
                            await db.get_active_threads())
    
    # 7. Print summary
    print(f"\n=== SIMULATION COMPLETE ===")
    print(f"Simulated: {days} days")
    print(f"Cycles: {cycle_count}")
    print(f"Consumes: {heartbeat._arbiter_state.consume_count_today}")  # last day only
    print(f"Threads created: {await db.count_threads()}")
    print(f"Totems: {await db.count_totems()}")
    print(f"Collection items: {await db.count_collection()}")
    print(f"Journal entries: {await db.count_journal_entries()}")
    print(f"DB: {sim_db}")
    print(f"Timeline: {log_path}")
```

### Heartbeat adaptation

`Heartbeat` needs a small refactor to support simulation:

```python
class Heartbeat:
    def __init__(self, clock=None, timeline=None):
        self._clock = clock
        self._timeline = timeline
    
    async def run_one_cycle(self) -> CycleResult:
        """Run exactly one autonomous cycle and return what happened.
        
        In production, this is called inside _main_loop.
        In simulation, called directly by simulate.py.
        """
        drives = await db.get_drives_state()
        focus = await decide_cycle_focus(drives, self._arbiter_state)
        
        # ... existing cycle execution ...
        
        return CycleResult(
            focus_channel=focus.channel,
            pipeline_mode=focus.pipeline_mode,
            detail=self._extract_detail(focus),
            actions=self._extract_actions(executor_result),
            sleep_seconds=random.randint(120, 600),
        )
```

The key: extract `run_one_cycle()` from the existing `_main_loop`. In production, `_main_loop` calls it in a `while True` with real sleeps. In simulation, `simulate.py` calls it in a `while clock < target` with clock advances.

---

## 9. POST-SIMULATION ANALYSIS

After simulation, the DB contains everything. Quick analysis tools:

```bash
# Inspect the sim DB
sqlite3 data/sim/sim_20250212_120000.db

# What threads survived the week?
SELECT title, status, touch_count, created_at, last_touched 
FROM threads ORDER BY touch_count DESC;

# What did she consume and like?
SELECT title, status, outcome_detail FROM content_pool 
WHERE status IN ('accepted', 'reflected') ORDER BY engaged_at;

# What did she ignore?
SELECT title, source_channel, tags FROM content_pool 
WHERE status = 'unseen' AND ttl_hours IS NOT NULL;

# Taste profile: what tags cluster in her totems?
SELECT json_each.value as tag, COUNT(*) as freq 
FROM totems, json_each(totems.tags) 
GROUP BY tag ORDER BY freq DESC;

# Thread lifespan distribution
SELECT title, 
       ROUND(julianday(last_touched) - julianday(created_at), 1) as days_alive,
       touch_count, status
FROM threads ORDER BY days_alive DESC;

# Feed engagement rate by source
SELECT json_extract(metadata, '$.site') as source,
       COUNT(*) as total,
       SUM(CASE WHEN status IN ('accepted','reflected') THEN 1 ELSE 0 END) as engaged,
       ROUND(100.0 * SUM(CASE WHEN status IN ('accepted','reflected') THEN 1 ELSE 0 END) / COUNT(*), 1) as engage_pct
FROM content_pool
WHERE source_channel = 'rss'
GROUP BY source ORDER BY engage_pct DESC;
```

These queries tell you:
- **Which feeds matter to her** (engagement rate by source)
- **What her taste profile looks like** (totem tag clustering)
- **Whether threads are forming and persisting** (carryover rate)
- **What she ignores** (candidates for removal from feed config)

---

## 10. BUILD ORDER

### Step 1: Clock abstraction
- `clock.py` with `Clock` class + module-level functions
- Replace all `datetime.now()` calls across codebase with `clock.now()` / `clock.now_utc()`
- **Verify:** production mode unchanged (default clock is real-time)

### Step 2: Heartbeat refactor
- Extract `run_one_cycle()` method from `_main_loop`
- Return `CycleResult` dataclass with focus_channel, actions, sleep_seconds
- `_main_loop` calls `run_one_cycle()` + real sleep (existing behavior)
- **Verify:** production heartbeat still works identically

### Step 3: Simulation infrastructure
- `simulate.py` entrypoint with CLI args
- Separate DB creation in `data/sim/`
- Content preloading from files
- `ingest.py --snapshot-feeds` command

### Step 4: Deterministic weather
- Simulation weather path in `pipeline/ambient.py`
- Day-level variation cycle
- **No network calls** when `clock.is_simulating()`

### Step 5: Timeline logger
- `timeline.py` with `TimelineLogger`
- Hook into cycle results (read-only inspection of executor output)
- Console output + log file

### Step 6: First simulation run
- Ingest `feb10-readings.txt` + RSS snapshot
- Run 3-day simulation
- Review timeline + run analysis queries
- Tune feeds, re-simulate

---

## 11. WHAT DOESN'T CHANGE

- Pipeline architecture (Sensorium → Thalamus → Cortex → Validator → Executor)
- Arbiter logic and caps (same rules in simulation as production)
- LLM calls are real (not mocked — she actually thinks)
- DB schema (same tables, separate file)
- Sleep cycle logic (fires at simulated 03:00 JST)
- All Living Loop behavior

---

## 12. RISKS / NOTES

- **LLM cost:** 7-day sim at ~12 cycles/day = ~84 cycles = ~84 Cortex calls. At ~2K tokens avg output, roughly 170K output tokens. Cheap enough for Sonnet, monitor if using Opus.
- **Rate limiting:** 84 calls in ~1 hour (real time) = ~1.4 calls/min. Well within API limits. The circuit breaker still works — it uses `clock.now()` so simulated daily caps reset at simulated midnight.
- **Pool exhaustion:** If pool runs dry mid-simulation, she falls back to idle/thread/express cycles. This is fine — it's realistic. But for best results, load 100+ items.
- **No visitor threads:** Threads from visitor interactions won't form in simulation. Her thread landscape will be consumption-driven only. This is a known gap — her identity will be richer in production when visitors add input.
- **Deterministic weather is simple:** The 7-day pattern repeats for longer simulations. For 14+ day sims, add more variation or randomize within ranges.
- **Sim DB accumulates:** Each run creates a new DB. Clean up old ones manually or add a `--clean` flag.

---

*Run her for a week in an hour. Watch the timeline scroll. See which headlines catch her eye, which threads she carries across days, what she puts in the backroom. Adjust the feeds. Run it again. By the time she goes live on the VPS, she already knows who she is.*
