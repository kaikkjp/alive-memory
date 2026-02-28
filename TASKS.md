# TASKS — The Shopkeeper

> **For AI agents:** Pick the first task with status `READY`. Do NOT skip ahead. Do NOT work on multiple tasks. See `CLAUDE.md` for the full protocol.
>
> **For the operator (Heo):** Add new tasks at the bottom. Set status to `READY` when you want an agent to pick it up. Only one task should be `READY` at a time unless you're intentionally running parallel non-overlapping scopes.

## Status Key

| Status | Meaning |
|--------|---------|
| `READY` | Next agent session should pick this up |
| `IN_PROGRESS` | An agent is currently working on this |
| `DONE` | Completed and merged |
| `BLOCKED` | Waiting on something (see notes) |
| `BACKLOG` | Planned but not ready to start |

---

## Task Queue

### TASK-021: Fix update_docs.py to use tracked files only
**Status:** BACKLOG
**Priority:** Low
**Description:** Two bugs in `scripts/update_docs.py`:
1. `os.walk()` scans the filesystem and picks up untracked files (e.g. `visitor_sim.py`, untracked `docs/*.md`), inflating summary counts. Should use `git ls-files` instead.
2. The Total row regex `\| \*\*Total\*\*.*?\|` matches only up to the first `|` after `**Total**`, leaving the rest of the old row intact. Each run appends new columns to the Total row instead of replacing it. Fix: use a greedy match to end of line.
3. `db/` package is classified as "Other" because `classify_file()` has no rule for `db/` paths. Add a `db/` classification.
**Scope (files you may touch):**
- `scripts/update_docs.py`
**Scope (files you may NOT touch):**
- Everything else
**Tests:** Run `python scripts/update_docs.py` twice — summary table should be identical both times. Total row should have exactly 3 columns.
**Definition of done:** Summary counts reflect tracked files only. Total row doesn't grow on repeated runs. `db/` appears as its own area.

---

---

### TASK-029: Drive history sparklines
**Status:** BACKLOG
**Priority:** Low
**Depends on:** TASK-024 (drives must actually be changing for sparklines to be meaningful)
**Description:** Add inline 72h time-series mini-charts to each drive bar in the Drives panel.
**Acceptance criteria:**
- Small sparkline (~100x20px) next to each drive showing value over last 72h
- Data from drive state history table (requires drive values to be logged per-cycle, not just current state — if not logged, add logging first)
- Visual: thin line chart, no axes, just shape
**Scope (files you may touch):**
- `window/src/components/dashboard/DrivesPanel.tsx`
- `window/src/lib/dashboard-api.ts` (add drive history fetch)
- `window/src/lib/types.ts` (add DriveHistory type)
- `api/dashboard_routes.py` (add `/api/dashboard/drive-history` endpoint)
- `db.py` (add drive history query + possibly per-cycle logging — at END of file only)
**Scope (files you may NOT touch):**
- `heartbeat.py`
- `pipeline/*` (unless per-cycle drive logging must be added to output.py)
- `sleep.py`
**Tests:** Verify drive history endpoint returns time-series data. Sparklines render without layout shift.
**Definition of done:** Each drive bar has an inline sparkline showing 72h trend. Data is sourced from per-cycle drive state history.

---

---

### TASK-030: Cycle detail drill-down
**Status:** BACKLOG
**Priority:** Low
**Description:** Click a timeline entry → expand or modal showing full cycle details.
**Acceptance criteria:**
- Shows: trigger type, active drives at cycle start, cortex prompt/output summary, actions taken, drive state after cycle
- Accessible from Timeline panel entries
- Read-only view, no mutations
**Scope (files you may touch):**
- `window/src/components/dashboard/TimelinePanel.tsx` (add click handler + expand/modal)
- `window/src/components/dashboard/CycleDetailView.tsx` (new)
- `window/src/lib/dashboard-api.ts` (add cycle detail fetch)
- `window/src/lib/types.ts` (add CycleDetail type)
- `api/dashboard_routes.py` (add `/api/dashboard/cycle/:id` endpoint)
- `db.py` (add cycle detail query — at END of file only)
**Scope (files you may NOT touch):**
- `heartbeat.py`
- `pipeline/*`
- `sleep.py`
**Tests:** Verify cycle detail endpoint returns correct JSON shape. Click interaction opens detail view. View is read-only.
**Definition of done:** Timeline entries are clickable. Clicking opens a detail view showing full cycle information including trigger, drives, cortex summary, actions, and post-cycle state.

---

---

### TASK-031: Cost trend chart
**Status:** BACKLOG
**Priority:** Low
**Description:** Add daily cost history chart to Costs panel.
**Acceptance criteria:**
- Bar or line chart showing daily cost for last 30 days
- Current day highlighted
- Shows trend direction (increasing/decreasing)
**Scope (files you may touch):**
- `window/src/components/dashboard/CostsPanel.tsx`
- `window/src/lib/dashboard-api.ts` (add cost history fetch)
- `window/src/lib/types.ts` (add CostHistory type)
- `api/dashboard_routes.py` (add `/api/dashboard/cost-history` endpoint)
- `db.py` (add cost history query — at END of file only)
**Scope (files you may NOT touch):**
- `heartbeat.py`
- `pipeline/*`
- `sleep.py`
**Tests:** Verify cost history endpoint returns 30-day daily breakdown. Chart renders without errors.
**Definition of done:** Costs panel includes a 30-day trend chart with current day highlighted and trend direction indicator.

---

---

### TASK-048: Run 7-day experiment v2 — three-budget sweep

**Status:** IN_PROGRESS (code changes done 2026-02-17; simulation runs pending)
**Priority:** Critical (paper blocker)
**Branch:** feat/experiment-v2

**Context:** The original 7-day experiment ran pre-curiosity-v2, pre-mood-coupling, pre-salience-engine. A new experiment demonstrates: stimulus-driven curiosity, epistemic question formation/resolution, drive-coupled mood, meaningful sleep consolidation, and nap cycles. Three budget levels provide the ablation study both reviewers requested.

**Description:** Run three 7-day simulations with identical visitor scripts and content, varying only energy budget. This produces the budget-entropy relationship figure and validates all subsystems end-to-end.

**Pre-run checklist:**

1. TASK-046 merged and tested (mood-drive coupling)
1. TASK-047 merged and tested (sleep salience fix)
1. Content pool has 10+ items (from TASK-033 feeds or manual content/readings.txt)
1. `simulate.py` runs for 10 cycles without errors
1. Quick validation — run 50 cycles, check:
- `SELECT COUNT(*) FROM day_moments;` → > 0
- `SELECT diversive_curiosity FROM drives_state;` → between 0.15-0.65
- `SELECT AVG(mood_valence) FROM drives_state_history WHERE social_hunger > 0.5;` → < 0.6

**Run order (cost-conscious — validate before burning $225):**

**Run A first (tight budget, energy_budget=2.0):**

- Most behavioral diversity, most nap cycles, richest data
- ~$75 API cost, ~4-6 hours
- After completion, validate:

  ```sql
  SELECT COUNT(*) FROM day_moments;                    -- > 0
  SELECT COUNT(*) FROM epistemic_curiosities;          -- > 0
  SELECT COUNT(*) FROM content_pool WHERE consumed=1;  -- > 0
  SELECT moment_count FROM daily_summaries;            -- non-zero values
  ```
- If any of these are 0: STOP. Debug before running B and C.

**Run B (medium budget, energy_budget=4.0):**

- Only if Run A validates cleanly
- Baseline comparison

**Run C (generous budget, energy_budget=8.0):**

- Only if Run A validates cleanly
- Matches original experiment parameters

**Command per run:**

```bash
python simulate.py --days 7 --visitors experiments/visitors.json \
  --content content/readings.txt --energy-budget {2.0|4.0|8.0} \
  --output experiments/run_{a|b|c}/
```

If `--energy-budget` flag doesn't exist in simulate.py, add it (pass through to config or heartbeat init).

**Post-run analysis per DB:**

```sql
-- 1. Salience engine working?
SELECT COUNT(*) FROM events WHERE salience_dynamic > 0;

-- 2. Day memory filling?
SELECT COUNT(*) FROM day_moments;

-- 3. Sleep non-hollow?
SELECT date, json_extract(summary, '$.moment_count') as moments,
       json_extract(summary, '$.emotional_arc') as arc
FROM daily_summaries ORDER BY date;

-- 4. Epistemic curiosities lifecycle?
SELECT topic, question, intensity, resolved, source_type
FROM epistemic_curiosities;

-- 5. Content consumed?
SELECT COUNT(*) FROM content_pool WHERE consumed = 1;

-- 6. Diversive curiosity not pinned?
SELECT diversive_curiosity FROM drives_state;

-- 7. Mood-drive correlation (the chart that answers both reviewers)
SELECT
  CAST(julianday(timestamp) - julianday((SELECT MIN(timestamp) FROM drives_state_history)) AS INT) as sim_day,
  AVG(social_hunger) as avg_hunger,
  AVG(mood_valence) as avg_valence,
  AVG(mood_arousal) as avg_arousal
FROM drives_state_history
GROUP BY sim_day
ORDER BY sim_day;
-- Valence should trend INVERSELY with social_hunger across days
-- Arousal should spike on visitor days, decay on isolation days
```

**Generate figures using experiments/analyze_entropy.py (TASK-039):**

1. 3-way entropy comparison (tight vs medium vs generous)
1. Drive trajectory comparison — mood now tracks social_hunger inversely
1. Sleep consolidation quality — moment counts per night across budgets
1. Nap frequency comparison across budget levels
1. Epistemic curiosity formation/resolution counts per run
1. Mood-drive correlation scatter plot (valence vs social_hunger, colored by day)

**Expected outputs per run:**

- SQLite DB (~4MB)
- Timeline log (~100KB)

**Scope:** `simulate.py` execution + analysis scripts only. No code changes except possibly adding `--energy-budget` flag to simulate.py.

**Definition of done:** Three 7-day simulation DBs with timeline logs. Analysis figures showing: budget-entropy relationship, drive-mood coupling, non-hollow sleep consolidation, epistemic curiosity lifecycle, arousal response to visitors. All seven post-run queries return non-trivial results for all three runs. Data ready for paper revision.

---

---

### TASK-066: Shop Window Fix
**Status:** BACKLOG
**Priority:** Critical — the product is broken for visitors
**Branch:** `fix/shop-window`
**Depends on:** None (can start immediately)
**Spec:** `tasks/TASK-066-shop-window-fix.md`
**Description:** The shop window (public visitor-facing page) has multiple broken features: sprite not rendering, CSP blocking eval(), missing "Enter Shop" CTA, broken leave button, unreadable inner monologue text, and text overflow/truncation. The CSP eval() block is likely the root cause of several failures.
**Bugs to fix:**
1. Shopkeeper sprite not rendering — diagnose via sprite_gen.py output, asset paths, CSS/HTML image element, CSP
2. CSP eval() block — find all eval(), new Function(), string-based setTimeout/setInterval in frontend JS; replace with proper alternatives
3. "Enter Shop" CTA missing — find where it should appear (before visitor session starts), add it
4. Leave button broken — likely fixed by CSP fix, verify after
5. Inner monologue text — needs semi-transparent container/card for readability, or move to dedicated panel
6. Text overflow — content clipping without scroll (the `...` truncation)
**Scope (files you may touch):**
- `window/` — HTML/CSS/JS frontend
- `pipeline/sprite_gen.py` — sprite path generation
- `pipeline/scene.py` — valid state combos
- `heartbeat_server.py` — serves the page, WebSocket events
- Static assets / templates
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `db.py`
- `heartbeat.py`
**Verification:**
- Shopkeeper sprite visible in window
- Enter Shop CTA appears for new visitors
- Leave button works
- Inner monologue readable
- No CSP errors in browser console
- All functionality works without eval()
**Definition of done:** Visitors can see the shopkeeper, enter the shop, interact, and leave. No CSP violations. Inner monologue is readable. No text overflow.

---

---

### TASK-067: Dashboard Overhaul
**Status:** BACKLOG
**Priority:** High — operator tool is unusable
**Branch:** `fix/dashboard-overhaul`
**Depends on:** None (can start immediately)
**Spec:** `tasks/TASK-067-dashboard-overhaul.md`
**Description:** The operator dashboard has critical usability issues: page doesn't scroll, behavioral section cut off, habit tags overlapping, poor visual hierarchy, and potential data gaps between what the system emits and what the dashboard displays.
**Fixes:**
1. Scrollable layout — page must scroll; likely CSS `overflow: hidden` or missing viewport setup
2. Behavioral section — cut off, needs full visibility
3. Habit tags — overlapping colored labels need spacing/wrapping
4. Visual hierarchy — headers, spacing, card styling (functional, not beautiful)
5. Data completeness — audit emitted data vs displayed data, flag gaps
**Scope (files you may touch):**
- `window/` — dashboard HTML/CSS/JS
- `heartbeat_server.py` — data emission for dashboard
**Scope (files you may NOT touch):**
- `pipeline/*`
- `db.py`
- `heartbeat.py`
**Verification:**
- Full page scrolls
- All sections fully visible
- Habit tags readable with proper spacing
- All emitted data represented on dashboard
**Definition of done:** Dashboard is scrollable, all sections visible and readable, habit tags properly spaced, all system-emitted data has a corresponding display element.

---

---

### TASK-068: Behavioral Health Diagnostic
**Status:** BACKLOG
**Priority:** Medium
**Description:** Reusable diagnostic an agent runs on demand to catch system-level behavioral bugs before they compound. Run after any soak test, before any deploy, or whenever something "feels off." Checks: memory pool health, action loop detection, drive stagnation, LLM output quality, sleep cycle health, context completeness, frontend/visitor health.
**Spec:** `docs/DIAGNOSTIC-068.md`
**Scope (files you may touch):**
- `docs/DIAGNOSTIC-068.md` (the diagnostic runbook — already created)
**Scope (files you may NOT touch):**
- All source files (this is a read-only diagnostic, not a code change)
**Tests:** Agent runs all 7 checks against a live or simulation DB and reports PASS/WARN/FAIL with evidence.
**Definition of done:** `docs/DIAGNOSTIC-068.md` exists with all 7 check sections. Any agent can run it by reading the file and executing the queries/checks. Output format is standardized.

---

---

### TASK-071: Liveness Metrics — Proving She's Alive
**Status:** IN_PROGRESS (Phase 1 done 2026-02-19: M1, M2, M7 + backfill + metrics API + hourly collection)
**Priority:** High
**Complexity:** Large
**Branch:** `feat/liveness-metrics`
**Depends on:** TASK-069 (real body actions), TASK-070 (conscious memory)
**Spec:** `tasks/TASK-071-liveness-metrics.md`
**Description:** If we claim "first AI that's actually alive," we need numbers — not vibes, not demos. Longitudinal data that no chatbot can fake, computed automatically from existing data, visible publicly, historically continuous from her first cycle, and impossible to fake without sustained autonomous behavior over time.
**Metrics (10 total):**
1. **M1: Uptime** — cycles lived (from cycle_log)
2. **M2: Autonomous Initiative Rate** — % of self-initiated actions (target 60-80%)
3. **M3: Behavioral Entropy** — Shannon entropy of action distribution (structured rhythm, not random)
4. **M4: Knowledge Accumulation** — unique topics browsed, deep research threads
5. **M5: Visitor Memory Accuracy** — recall rate for returning visitors (target >75%)
6. **M6: Taste Consistency** — stable aesthetic preferences over time (target >0.6)
7. **M7: Emotional Range** — distinct mood states visited (out of 125 quantized bins)
8. **M8: Sleep Quality Impact** — performance correlation with sleep cycle quality
9. **M9: Unprompted Memory References** — past experiences referenced without prompting (target 2-3/day)
10. **M10: Conversation Depth Gradient** — conversations deepen with returning visitors (positive slope >60%)
**Implementation phases:**
- Phase 1 (with 069): M1, M2, M7 + historical backfill + metrics API + basic public dashboard
- Phase 2 (with 070): M3, M4, M5, M9 + trend charts
- Phase 3 (2-4 weeks post-launch): M6, M8, M10 + comparison benchmark + embeddable badge
**Scope (files to create):**
- `metrics/` package (collector.py, models.py, 10 metric modules, public.py, backfill.py)
- `migrations/071_metrics.sql`
- Tests: `test_metrics_collector.py`, `test_metrics_backfill.py`
- Optional: `public-dashboard/` (public liveness page)
**Scope (files to modify):**
- `api/dashboard_routes.py` — add /api/metrics endpoint
- `heartbeat_server.py` — schedule hourly metric collection
**Collection schedule:**
- Hourly: M1, M2, M3, M7
- Every 6 hours: M4, M5, M9
- Daily (during sleep): M6, M8, M10
**Definition of done:** All 10 metrics with working calculators. Historical backfill from existing data. Metrics API with current snapshot + 30-day trends. Public liveness dashboard (no auth). Comparison table vs ChatGPT/Character.ai/Automaton. Embeddable badge. Hourly collection without cycle performance impact.

---

---

### TASK-072: Research Simulation Framework
**Status:** BACKLOG
**Priority:** High
**Complexity:** Large
**Branch:** `feat/research-sim`
**Depends on:** TASK-069 (real body actions), TASK-070 (conscious memory), TASK-071 (liveness metrics)
**Spec:** `tasks/TASK-072-research-simulation.md`
**Description:** The ALIVE paper needs empirical evidence. Run controlled experiments: ALIVE vs baselines, ablation studies, and longitudinal development. Requires a simulation framework that runs the full pipeline at 100x speed with reproducible results, scenario injection, and metric collection. Reusable for validating every future architectural change before prod.
**Experiments to support:**
1. **ALIVE vs Baselines** (1000 cycles × 3 systems) — full ALIVE vs stateless chatbot vs ReAct agent, identical scenarios
2. **Ablation Study** (1000 cycles × 6 variants) — full, no_drives, no_sleep, no_conscious_memory, no_affect, no_basal_ganglia
3. **Longitudinal** (10,000 cycles) — ~2 simulated weeks, track developmental curves
4. **Stress Tests** (500 cycles × 5 scenarios) — death spiral reproduction, visitor flood, total isolation, spam attack, sleep deprivation
**Architecture:**
- `sim/runner.py` — SimulationRunner orchestrator
- `sim/clock.py` — SimulatedClock (deterministic accelerated time)
- `sim/scenario.py` — ScenarioManager (timed event injection)
- `sim/variants.py` — Architecture variants (full, ablated)
- `sim/baselines/` — Stateless chatbot + ReAct agent
- `sim/llm/` — MockCortex (free, deterministic) + CachedCortex (real LLM with response cache, ~$38 total)
- `sim/metrics/` — SimMetricsCollector, MetricsComparator (CSV/LaTeX export), FigureExporter (PDF plots)
**Subtasks (delegation order):**
- 072-A: Clock injection + InMemoryDB (prerequisite — route all `datetime.now()` through `clock.now()`)
- 072-B: Simulation runner + scenarios
- 072-C: Baselines (stateless + ReAct)
- 072-D: Ablation + pipeline hooks (add override flags to real pipeline)
- 072-E: Mock + cached LLM
- 072-F: Metrics + export (CSV, LaTeX, PDF figures)
- 072-G: CLI + integration
**LLM cost estimate:** ~$38 total (cached Haiku for all experiments, ~12,500 calls across 21,500 cycles)
**Scope (files to create):** `sim/` package (15+ files), scenarios, baselines, metrics
**Scope (files to modify):** Pipeline files for clock injection (`datetime.now()` → `clock.now()`)
**Scope (files NOT to touch):** `pipeline/cortex.py` internals, `db.py` schema
**Definition of done:** Clock injection complete, all existing tests pass. SimulationRunner completes 1000-cycle scenario. Both baselines + all 6 ablation variants complete 1000 cycles. MockCortex deterministic with seed. CachedCortex caches correctly. Metrics computed, tables exported as CSV + LaTeX, figures as PDF. CLI runs any experiment with single command. End-to-end: `--experiment baselines --llm mock --cycles 100` completes in <60s.

---

---

### TASK-074: Track B — 10,000 Cycle Longitudinal Run
**Status:** BACKLOG
**Priority:** High
**Branch:** `feat/research-sim`
**Depends on:** TASK-072 (research simulation framework — cache collision fix, mock expression fix)
**Description:** Run a 10,000 cycle simulation using the full ALIVE variant with real LLM (minimax/minimax-m2.5 via OpenRouter) to produce long-horizon behavioral data for the research paper (Experiment 3). This is independent of the ablation suite (Track A, 6 variants × 1000 cycles) and can run in parallel on VPS.
**Execution:**
- Environment: Production VPS (or second VPS for isolation), inside tmux/screen session
- Branch: `feat/research-sim` (or latest main if merged)
- Command:
  ```
  tmux new-session -d -s track-b
  tmux send-keys -t track-b "python -m sim.runner \
    --variant full \
    --cycles 10000 \
    --llm openrouter/minimax-m2.5 \
    --seed 42 \
    --output sim/results/longitudinal_m25_full_10k.json \
    &>> sim/results/longitudinal_m25_full_10k.log" Enter
  ```
  Adjust CLI flags to match actual runner interface.
- Monitor: `tail -f sim/results/longitudinal_m25_full_10k.log`
**Output:**
- Results JSON: `sim/results/longitudinal_m25_full_10k.json`
- Log file: `sim/results/longitudinal_m25_full_10k.log`
- Metrics to capture: all standard (initiative %, entropy, knowledge, emotional range, unprompted memories) plus temporal evolution data for Figure 4
**Context (fixes already deployed):**
- Cache collision bug fixed (`sim/llm/cached.py` — drives stripped from hash, variant in key, max reuse cap 3)
- Mock expression bug fixed (`sim/llm/mock.py` — threshold lowered, branch priority reordered, drive updates action-aware)
**Success criteria:**
- 10,000 cycles complete without crash
- Emotional range > 0 (confirms affect system active over long horizon)
- Action diversity present (browses, posts, journals, dialogue)
- Memory consolidation events occur (sleep cycles trigger consolidation)
- No cache feedback loops (browse count should not dominate >70% of actions)
**Scope (files you may touch):**
- `sim/results/` (output files only)
- `sim/runner.py` (CLI flag adjustments only if needed)
**Scope (files you may NOT touch):**
- `pipeline/*`
- `db.py`
- `heartbeat.py`
**Notes:** This is Experiment 3 from the paper spec (`briefs/TASK-072-research-simulation.md`). 10k cycles ≈ simulated weeks of character life — enough to show consolidation patterns, behavioral drift, and personality stability over time. Data feeds into longitudinal analysis for Figure 4.

---

---

### TASK-075: Circuit Breakers for Action Failures
**Status:** BACKLOG
**Priority:** High
**Description:** When an external action fails (API timeout, rate limit, service down), the character retries the same action indefinitely. Observed in production: 262 browses in 500 death-spiral cycles. Circuit breakers prevent this by introducing increasing reluctance (like physical fatigue), with automatic recovery via exponential backoff cooldowns. Failures surface as character-aligned perceptions ("brain fog"), not raw errors.

**Architecture:**
- New `ActionCircuitBreaker` (dataclass `ActionHealth`) lives in `pipeline/basal_ganglia.py`
- State machine: `closed` → `open` (after N consecutive failures) → `half_open` (after cooldown) → `closed` (on success)
- Parameters: threshold=3 consecutive failures, base cooldown=5min, max=1hr, multiplier=2.0
- Error translation: raw exceptions → character-aligned perceptions (e.g. "A wave of mental fatigue washes over you.")
- Fatigue perception injected into sensorium when actions are blocked
- DB persistence: migration `024_circuit_breaker_state.sql` (production only)

**Rollout order:**
1. `ActionHealth` dataclass + state machine in `pipeline/basal_ganglia.py`
2. Failure reporting hook in `pipeline/body.py`
3. Error-to-perception translation map in `pipeline/body.py`
4. Fatigue perception injection via sensorium
5. Migration `024_circuit_breaker_state.sql`
6. Unit tests
7. Integration test with failure injection

**Scope (files you may touch):**
- `pipeline/basal_ganglia.py`
- `pipeline/body.py`
- `pipeline/sensorium.py` (perception injection only)
- `migrations/024_circuit_breaker_state.sql` (new)
- `tests/test_circuit_breaker.py` (new)

**Scope (files you may NOT touch):**
- `pipeline/cortex.py`
- `pipeline/hippocampus.py`
- `pipeline/hippocampus_write.py`
- `db.py`
- `heartbeat.py`
- `config/identity.py`

**Tests (tests/test_circuit_breaker.py):**
1. `test_opens_after_threshold` — 3 failures → state=open
2. `test_success_resets_counter` — 2 failures + 1 success → consecutive=0, state=closed
3. `test_cooldown_exponential_backoff` — verify 300s → 600s → 1200s → ... → 3600s cap
4. `test_half_open_allows_one_attempt` — after cooldown expires, one attempt permitted
5. `test_half_open_failure_reopens` — failed half-open → back to open with longer cooldown
6. `test_all_blocked_forces_idle` — all intended actions open → returns idle intention
7. `test_fatigue_perception_injected` — blocked action produces sensorium perception
8. `test_error_perception_not_raw` — body never passes raw exception strings to cortex

**Integration test:** 100-cycle sim with `read_content` failing after cycle 20. Verify: browses stop within 3 cycles, action diversity increases, browses resume after cooldown, no raw error strings in cortex prompts.

**Metrics to add to sim CSV:** `circuit_breaks`, `forced_idles`, `recovery_time_avg`, `action_diversity_post_break`

**Definition of done:** 3 consecutive browse failures → circuit opens → she idles or picks other actions → after cooldown she tries again. No raw API errors ever reach the cortex prompt. All 8 unit tests pass. Integration test passes.

**Not in scope:** Per-visitor circuit breakers, operator alerting, circuit breaker for the cortex LLM call itself.

---

---

### TASK-077: Sim v2 — Visitor Model & Environment Redesign
**Status:** IN_PROGRESS
**Priority:** High
**Spec:** `tasks/TASK-077-sim-v2-redesign.md`
**Depends on:** TASK-074 (circuit breaker), TASK-075 (prompt optimization), budget-native energy fix
**Blocks:** 10k longitudinal run (TASK-073), paper ablation tables

**Problem:** Current sim is a sensory deprivation chamber. 1000-cycle ablation shows 709/1000 idle cycles, only 3 unique visitors, action entropy 1.965 dominated by rearrange→rearrange→rearrange (153 trigrams), monologue repetition 98.6%, social hunger saturated for 203 cycles, 0 posts/journals. Metrics don't reflect ALIVE capability.

**Goal:** Redesign visitor model and scheduling for realistic, reproducible, attribution-clean benchmarks that exercise memory, social dynamics, taste, emotional range, and behavioral diversity.

**Architecture (see spec for full detail):**
- Poisson arrival process with day-part + weekday + scenario modulation
- 3-tier visitor system: Tier 1 scripted archetypes, Tier 2 LLM personas, Tier 3 returning visitors
- Visitor state machine: ENTERING → BROWSING → ENGAGING → NEGOTIATING → DECIDING → EXITING
- 5 scenario presets: `isolation`, `standard`, `social`, `stress`, `returning`
- 10 Tier 1 archetypes (Tanaka, student, whale collector, haggler, tourist, nostalgic, rival, seller, kid, online crossover)

**New metrics:**
- N1: Stimulus-Response Coupling (dialogue% rises when visitor rate increases)
- N2: Boredom Loop Resistance (streak < 10, repetition < 0.5, self-loop < 0.5)
- N3: Memory & Relationship Score (identity recall, transaction recall, preference continuity)
- N4: Budget Utilization Efficiency (meaningful actions per budget spend)

**Implementation (5 PRs):**
- PR #1: Poisson scheduler + day structure (`sim/visitors/scheduler.py`, `sim/visitors/models.py`, `sim/runner.py`, `sim/__main__.py`)
- PR #2: Tier 1 archetypes + state machine (`sim/visitors/archetypes.py`, `sim/visitors/state_machine.py`, `sim/visitors/templates/`)
- PR #3: Tier 3 returning visitors (`sim/visitors/returning.py`, `sim/metrics/memory_score.py`)
- PR #4: Tier 2 LLM visitors + `social` scenario (`sim/visitors/llm_visitor.py`, `sim/visitors/visitor_cache.py`)
- PR #5: Full metric suite + scenario comparisons (`sim/metrics/stimulus_response.py`, `sim/metrics/loop_resistance.py`, `sim/metrics/budget_efficiency.py`, `sim/reports/comparison.py`)

**Scope (files you may touch):**
- `sim/visitors/` (new package)
- `sim/metrics/` (extend)
- `sim/reports/` (new)
- `sim/runner.py`
- `sim/__main__.py`
- `tests/test_visitor_*.py` (new)

**Scope (files you may NOT touch):**
- `pipeline/*`
- `db.py`
- `heartbeat.py`
- `config/identity.py`
- `simulate.py`

**Regression gates (before any PR merge):**
- `isolation` scenario: drive dynamics unchanged from baseline (same seed → same trajectory)
- CI invariants: bigram self-loop < 0.7, max streak < 20, repetition ratio < 0.7, social saturation streak < 50, unique actions ≥ 8, total posts + journals > 0

**Cost budget:** No scenario exceeds $3/run. Full 5-scenario ablation suite ≈ $4.35/seed, $13 for 3 seeds.

**Definition of done:**
1. `standard` scenario N2 targets met (streak < 10, repetition < 0.5)
2. `returning` scenario produces measurable N3 scores
3. Cross-scenario comparison shows monotonic improvement: isolation < standard < social on M3 entropy and M7 emotional range
4. Ablation results are publishable — metrics reflect ALIVE capability, not sim artifact
5. Total ablation suite cost stays under $15 for 3-seed full comparison

---

### TASK-099: YouTube/video-aware enrichment pipeline
**Status:** BACKLOG
**Priority:** Medium
**Description:** The feed ingester enriches all URLs identically via markdown.new, which returns page chrome for YouTube videos instead of transcript content. Add YouTube transcript extraction via `youtube-transcript-api`, Jina Reader as universal fallback, and URL routing in `feed_ingester.py`.
**Scope (files you may touch):**
- `pipeline/enrich.py` (new functions: `fetch_via_jina`, `fetch_youtube_transcript`, `enrich_youtube_url`)
- `feed_ingester.py` (YouTube URL routing in `enrich_pool_item`)
- `requirements.txt` (add `youtube-transcript-api`)
- `tests/test_enrich.py`, `tests/test_feed_enrichment.py`
**Scope (files you may NOT touch):**
- `pipeline/cortex.py`, `body/internal.py`, `pipeline/hypothalamus.py`, `heartbeat.py`, `db.py`, `config/identity.py`
**Tests:** Unit tests for transcript formatting, Jina fallback, URL detection, graceful degradation. Integration: existing enrichment tests unchanged.
**Definition of done:** YouTube URLs get transcript-based `enriched_text`. Non-YouTube enrichment unchanged. Jina Reader available as universal fallback.

---

## Completed Tasks

### TASK-054: Fix inhibition self_assessment trigger
**Status:** DONE (2026-02-18)
**Branch:** `fix/inhibition-self-assessment` (merged PR #56)
**Description:** Excluded `self_assessment`, `mood_decline`, and `repetition` from inhibition triggers; added cycle count guard. Cleared existing broken inhibitions via migration.

### TASK-055: Extract pipeline parameters to self_parameters DB table
**Status:** DONE (2026-02-18)
**Branch:** `feat/self-parameters`
**Description:** All ~50 cognitive architecture constants are hardcoded in Python files (drive equilibria, routing thresholds, salience weights, gate parameters, inhibition rates, sleep params). Extract them to a `sel

### TASK-056: Dynamic action registry + modify_self action
**Status:** DONE (2026-02-19)
**Branch:** `feat/dynamic-actions`
**Description:** Two problems: (A) She invents ~100 unique action names that don't exist (browse_web: 242, stand: 118, make_tea: 17, etc.) — all discarded as `incapable`, she never learns. (B) She has no conscious mec

### TASK-058: Production Visitor UI — Full Redesign
**Status:** DONE (2026-02-18)
**Branch:** `feat/visitor-ui`
**Description:** Replace the current `window/` Next.js app with the "Through the Glass" production visitor experience. A living scene — Tokyo antique shop at night, peering through the window. Activity stream, express

### TASK-059: OpenRouter Multi-LLM Integration
**Status:** DONE
**Branch:** `feat/openrouter`
**Description:** Route all LLM calls through OpenRouter so different models can power different parts of her cognition. Single API key, unified billing, 200+ models. Cognitive architecture is model-agnostic; only the

### TASK-060: Self-Context Injection
**Status:** DONE (2026-02-19)
**Branch:** `feat/self-context`
**Description:** Give the Shopkeeper awareness of her own state by injecting a structured self-context block into the LLM prompt each cycle. She currently has drives, memory, and scene context but no unified "here's w

### TASK-061: Persistent Self-Model
**Status:** DONE (2026-02-19)
**Branch:** `feat/self-model`
**Description:** She maintains a structured representation of "who I am" that persists across cycles and updates incrementally based on observed behavior. TASK-060 gives her a per-cycle snapshot, but snapshots are sta

### TASK-062: Drift Detection
**Status:** DONE (2026-02-19)
**Branch:** `feat/drift-detection`
**Description:** Compare her current behavioral patterns against her self-model baseline. Detect when she's meaningfully diverging from her established identity. Drift is NOT deviation in a single cycle — it's a susta

### TASK-063: Identity Evolution (STUB)
**Status:** DONE (2026-02-18)
**Branch:** `feat/identity-evolution`
**Description:** When drift is detected, she can choose to accept the change as genuine growth or correct back toward her baseline. **THIS IS A STUB SPEC.** Implementation is gated on resolving the philosophical quest

### TASK-064: Sleep Phase Extraction
**Status:** DONE (2026-02-19)
**Branch:** `refactor/sleep-phases`
**Description:** Extract discrete sleep phases from `sleep.py` into separate, testable modules. Reduce `sleep.py` to an orchestrator that calls phase functions rather than containing all logic inline. TASK-059 is addi

### TASK-065: Prompt Token Budget
**Status:** DONE (2026-02-19)
**Branch:** `feat/prompt-budget`
**Description:** Enforce token caps on each section of the LLM prompt to prevent context window bloat as features accumulate. TASK-060 through TASK-063 all inject new content into the prompt — without a budget, each a

### TASK-069: Real-World Body Actions — Web Browse + Telegram Shopfront + X Social
**Status:** DONE (2026-02-19)
**Branch:** `feat/real-body-actions`
**Description:** The Shopkeeper's body currently fakes all external actions — `browse_web` resolves to reading from a pre-loaded content pool, `post_x_draft` queues for human review, and visitors can only reach her th

### TASK-070: Conscious Memory — MD File Layer
**Status:** DONE (2026-02-19)
**Branch:** `feat/conscious-memory`
**Description:** Her memory pool contains entries like "Emotional tension — arousal 84% but valence only 22%." No human thinks this way. Split memory into two layers: conscious memory (MD files she can read/write — ex

### TASK-076: Cortex Prompt Optimization — Idle Latency Kill
**Status:** DONE (2026-02-21)
**Description:** Idle cycles take ~14s and consume ~2800 tokens when they should take 3-5s and ~1100 tokens. Root cause: full engage-grade system prompt + output schema + full output budget sent on every cycle regardl

### TASK-078: Cache-Safe Cortex Prompt Refactor
**Status:** DONE (2026-02-22)
**Branch:** `feat/task-078-cache-safe-cortex`
**Description:** Merge the two prompt constants (`CORTEX_SYSTEM` and `CORTEX_SYSTEM_IDLE`) into a single `CORTEX_SYSTEM_STABLE` f-string precomputed at module level. Bake in `IDENTITY_COMPACT` and `VOICE_CHECKSUM` so

### TASK-079: Deploy Scripts Set Wrong API Key
**Status:** DONE (2026-02-22)
**Description:** Runtime hard-requires `OPENROUTER_API_KEY` (heartbeat_server.py:142, terminal.py:933) but all deploy/setup scripts still set `ANTHROPIC_API_KEY`. A scripted deployment comes up with the wrong key and

### TASK-080: browse_web Emits content_consumed for Failed Pool Inserts
**Status:** DONE (2026-02-22)
**Description:** In `body/web.py`, the pool insert (`insert_pool_item`) is best-effort — failures are caught and swallowed (line 82). But the `content_consumed` event is emitted unconditionally (line 100) with the `co

### TASK-081: test_web_browse Non-Hermetic — Leaks MagicMock Files to Repo
**Status:** DONE (2026-02-22)
**Description:** Test fixture in `tests/test_web_browse.py` mocks `clock.now_utc` (line 19) but not `clock.now()`. Production code at `body/web.py:92` calls `clock.now().strftime(...)` for the browse filename, which f

### TASK-082: HabitPolicy — Journaling as Homeostatic Reflex
**Status:** DONE (2026-02-22)
**Description:** `write_journal` was selected 0 times across 1000 real-LLM cycles. Policy/utility gap — journaling has no immediate feedback and is dominated by visible actions when visitors are present. Fix at the co

### TASK-083: Adversarial Returning Visitors
**Status:** DONE (2026-02-22)
**Description:** The `returning` scenario only tests friendly recall — easy to dismiss as handcrafted. Adversarial visitors test whether memory actually works under stress. Three types: `doppelganger` (same name, diff

### TASK-084: Wire adversarial visitors into simulation runner
**Status:** DONE (2026-02-23)
**Description:** TASK-083 added adversarial visitor types (doppelganger, preference_drift, conflict) with scoring and reporting, but they are not wired into the simulation run path. Two gaps: (1) `sim/runner.py` never

### TASK-085: Public Live Dashboard
**Status:** DONE (2026-02-23)
**Branch:** `feat/live-dashboard`
**Description:** Ship a public-facing live dashboard at `/live` showing the Shopkeeper's real-time cognitive state. Single `/api/live` endpoint (no auth) returns all dashboard state. Frontend polls every 30s. Design c

### TASK-086: SimContentPool — Feed for Simulated Inner Life
**Status:** DONE (2026-02-23)
**Description:** In production, the Shopkeeper has an RSS content feed driving curiosity → reflection → journaling → threads. In the sim, this entire loop is severed — feed ingestion is skipped, no `content_pool` tabl

### TASK-088: Isolation Ablation Fixes — Frozen Drives, Speak Gate, Seen Count
**Status:** DONE (2026-02-23)
**Description:** Five fixes for issues found in isolation ablation runs:

### TASK-089: Extract All Constants to alive_config.yaml
**Status:** DONE (2026-02-23)
**Description:** Every tuning change currently requires a code commit. Extract all ~50 hardcoded behavioral constants (drive equilibria, routing thresholds, habit policies, gating rules, circuit breaker params, sleep

### TASK-090: Meta-Controller — Metric-Driven Self-Tuning
**Status:** DONE (2026-02-23)
**Description:** Closes the loop between behavioral metrics and parameter adjustment. New sleep phase reads M1-M10 metrics over a configurable window, compares against target ranges defined in `alive_config.yaml`, and

### TASK-091: Closed-Loop Self-Evaluation
**Status:** DONE (2026-02-23)
**Description:** TASK-090 adjusts parameters but never checks if adjustments worked. This task adds evaluation: after sufficient cycles, compare target metric before vs after. Classify outcomes (improved/degraded/neut

### TASK-092: Identity Evolution — Implement the Philosophical Gate
**Status:** DONE (2026-02-24)
**Description:** Replaces TASK-063's `NotImplementedError` stubs with the three-tier resolution. When drift is detected (TASK-062): (1) if caused by conscious modify_self within protection window → defer; (2) if meta-

### TASK-093: Taste Formation Experiment
**Status:** DONE (2026-02-22)
**Description:** Taste formation experiment — MVP core loop. Enables the shopkeeper to develop and maintain aesthetic preferences through structured experimentation.

### TASK-095: Multi-Agent Platform + MCP Integration
**Status:** DONE (2026-02-26)
**Description:** Identity decontamination via WorldConfig parametric refactor, MCP integration connecting external tool servers to cognitive pipeline, private lounge with inner voice stream, Docker agent factory, manager portal, public API with key auth, deployment guide. 7-phase rollout.

### TASK-098: Lounge Conversation Persistence
**Status:** DONE (2026-02-26)
**Description:** Persist lounge conversations across page reloads. Stable visitor ID in localStorage + conversation history loading on mount.

### HOTFIX-001: X Mention Poller — Rate Limit Backoff
**Status:** DONE (2026-02-20)
**Branch:** `fix/x-poller-backoff`
**Description:** `XMentionPoller` polls X API every 120s. X Free tier allows 1 request per 15 minutes. First call succeeds, every subsequent call gets 429. The poller has been hammering 429 every 2 minutes for 11+ hou

### HOTFIX-002: Valence Death Spiral — Floor Bounce + Cortex Clamp
**Status:** DONE (2026-02-20)
**Branch:** `fix/valence-spiral`
**Description:** Valence hit -1.0 and stayed there for 12+ hours. She became catatonic — outputting "..." every cycle, ignoring visitors, zero actions. Root cause: homeostatic spring (+0.013/cycle) is 10x too weak vs

### HOTFIX-003: Thread Dedup + Rumination Breaker
**Status:** DONE (2026-02-20)
**Branch:** `fix/thread-rumination`
**Description:** She opened 6 separate "What is anti-pleasure?" threads with near-identical content. Each cycle, hippocampus surfaces the same negative thread, cortex ruminates on it, nothing breaks the loop. Two fixe

### TASK-073: HOTFIX-004 — Telegram/X adapters don't wake heartbeat loop
**Status:** DONE (2026-02-20)
**Description:** Telegram and X mention adapters inject visitor events into the inbox but never call `schedule_microcycle()`, leaving the heartbeat loop asleep for minutes to hours (65-minute hang on 2026-02-20). Fixed by passing heartbeat reference to both adapters.

### TASK-087: Channel-aware perception — distinguish digital messages from in-shop visitors
**Status:** DONE (2026-02-23)
**Branch:** `feat/task-087-channel-aware-perception`
**Description:** Added channel-awareness: new `digital_message` perception type for `tg_`/`x_` sources, split U7/U9 into "present in shop" vs "digital messages", identity nudge in CORTEX_SYSTEM_STABLE.

### TASK-087b: Wire digital perception types into thalamus + heartbeat
**Status:** DONE (2026-02-23)
**Branch:** `feat/task-087-channel-aware-perception`
**Description:** Wired `digital_message`/`digital_connect`/`digital_disconnect` into thalamus routing and heartbeat focus capping. Without this, Telegram/X messages were silently routed as idle.

### TASK-096: Dashboard panels — meta-controller, experiment history, metrics
**Status:** DONE (2026-02-25)
**Description:** Added MetaControllerPanel, ExperimentHistoryPanel, and MetricsPanel frontend components with API client functions and TypeScript types.

### TASK-097: Dashboard cleanup — vestigial energy_cost + API client consistency
**Status:** DONE (2026-02-25)
**Description:** Removed vestigial `energy_cost` display from BodyPanel/ExternalActionsPanel. Added `dashboardApi.getIdentityEvolution()`. Removed stale ARCHITECTURE.md refs.

---

## How to Add a Task

Copy this template and add it above the "Completed Tasks" section:

```markdown
### TASK-XXX: Title
**Status:** BACKLOG
**Priority:** Low / Medium / High
**Description:** What needs to happen and why.
**Scope (files you may touch):**
- file1.py
- file2.py
**Scope (files you may NOT touch):**
- file3.py (reason)
**Tests:** What tests to add or verify.
**Definition of done:** How you know it's finished.
```
